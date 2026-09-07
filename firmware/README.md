# ESP32 엣지 제어기 펌웨어

스마트팜 센서값을 읽어 서버로 올리고, 서버가 내린 명령으로 워터펌프·환기팬·
조명 릴레이를 미는 펌웨어다 (SPEC 6.2 / 7.2).

**판단은 서버가 한다.** 작물별 기준값(`crop_thresholds`)과 히스테리시스 상수는
서버 한 곳(`backend/app/services/smartfarm.py`)에만 있고 펌웨어에 복제하지
않는다. 예외는 **오프라인 안전 제어** 하나뿐이며, 그 규칙은 아래
[오프라인 안전 규칙](#오프라인-안전-규칙)에 그대로 적혀 있다.

전체 계약은 [docs/ARCHITECTURE.md 11절](../docs/ARCHITECTURE.md#11-스마트팜-자동제어-계약-spec-55--72)이다.

---

## 하는 일

1. 온습도·조도·토양수분을 30초마다 읽어 `sensor/data` 로 발행한다.
2. `control/command` 를 구독해 릴레이를 그대로 민다.
3. 연결이 끊기면 보수적인 오프라인 안전 제어로 넘어간다.
4. 복귀하면 오프라인 동안 한 동작을 서버에 보고한다.

```
[DHT22 · BH1750 · 토양수분]
        │ 30초마다
        ▼
     ESP32 ──── Wi-Fi ──── Mosquitto ──── FastAPI 서버
        │        sensor/data  ▲                 │ crop_thresholds 와 비교
        │                     └── control/command ◀──┘
        ▼
  릴레이 모듈 → 워터펌프 / 환기팬 / 조명
```

---

## 배선표

ESP32 DevKit v1 (30핀) 기준이다. 핀 번호는 GPIO 번호이며,
[`include/config.h`](include/config.h) 에서 `-D` 플래그로 덮어쓸 수 있다.

### 센서

| 센서 | 측정 항목 | 부품 | ESP32 핀 | 비고 |
|---|---|---|---|---|
| 온습도 | 온도(℃) · 습도(%) | DHT22 (AM2302) | **GPIO 4** (DATA) | DATA–VCC 사이에 10kΩ 풀업 |
| 조도 | 조도(lx) | BH1750 (I2C) | **GPIO 21** (SDA) · **GPIO 22** (SCL) | 주소 0x23 (ADDR 미결선) |
| 토양수분 | 토양수분(%) | 정전용량식 v1.2 | **GPIO 34** (AOUT) | ADC1 — Wi-Fi 와 동시 사용 가능 |

BH1750 대신 LDR 분압을 쓰려면 `-DUSE_BH1750=0 -DPIN_LUX_ADC=35` 로 빌드한다.

### 구동장치 (릴레이 모듈)

| 구동장치 | 릴레이 채널 | ESP32 핀 | 서버 `device` 값 |
|---|---|---|---|
| 워터펌프 | IN1 | **GPIO 26** | `pump` |
| 환기팬 | IN2 | **GPIO 27** | `fan` |
| 조명 | IN3 | **GPIO 25** | `light` |

저가 릴레이 모듈은 대부분 **active-LOW**(LOW 에서 접점이 닫힌다). 보드가
active-HIGH 면 `-DRELAY_ACTIVE_LOW=0` 으로 빌드한다.

### 전원과 그 밖

| 항목 | 연결 | 비고 |
|---|---|---|
| 센서 전원 | 3V3 / GND | DHT22 는 5V 도 되지만 3V3 로 통일한다 |
| 릴레이 모듈 VCC | **5V** | ESP32 3V3 레귤레이터로는 코일 전류를 못 댄다 |
| 릴레이 모듈 GND | GND 공통 | ESP32 와 반드시 공통 접지 |
| 펌프·팬·조명 전원 | **별도 전원** | 릴레이 접점 쪽. ESP32 전원과 분리한다 |
| 상태 LED | GPIO 2 (온보드) | 점등 = 서버 제어 중 · 깜빡임 = 오프라인 |

> ⚠️ 릴레이 접점 쪽에 AC 를 물릴 때는 절연·퓨즈·차단기를 반드시 갖춘다.
> 프로토타입 실증은 DC 12V 펌프/팬으로 시작하기를 권한다.

---

## 오프라인 안전 규칙

SPEC 6.2 의 "인터넷 연결이 끊겨도 설정된 안전 기준에 따라 펌프 및 환기장치를
제한적으로 제어한다" 를 구현한 것이다. 목표는 **작물을 살리는 것**이지 서버를
흉내내는 것이 아니다. 코드는
[`lib/farmcontrol/offline_control.cpp`](lib/farmcontrol/offline_control.cpp) 에
있고, Arduino 의존성이 없어 호스트에서 그대로 테스트된다.

### 1. 오프라인 판정

다음 중 하나면 오프라인이다.

- Wi-Fi 나 브로커 연결이 끊겼다.
- 마지막 `control/command` 수신 이후 **측정 주기의 3배(기본 90초)** 가 지났다.

한 번도 명령을 받은 적이 없는 갓 부팅 상태는 오프라인으로 보지 않는다.
적정 범위 안이라 서버가 보낼 명령이 없는 것이 정상이기 때문이다.

**복귀하면 즉시 판단 권한을 서버에 돌려준다** — 오프라인 동안 *자기가 켠*
릴레이를 모두 끄고, 이후는 `control/command` 만 따른다. 서버가 켜 둔 릴레이는
건드리지 않는다.

### 2. 기준값 출처

1. 서버가 `control/command` 에 실어 보낸 기준값 → NVS(`farmflow` 네임스페이스)에
   저장한 사본
2. 사본이 없으면 펌웨어 컴파일 상수 (`FALLBACK_*`, SPEC 5.5 의 토마토 기준:
   22–27℃ / 60–75% / 토양수분 35–55% / 조도 15,000lx)

> 현재 서버는 명령에 기준값을 싣지 않는다. 그래서 실사용 경로는 2번이며,
> 1번은 서버가 나중에 `thresholds` 를 덧붙일 때를 위한 것이다. 필드가 추가
> 되어도 펌웨어를 다시 굽지 않아도 된다.

### 3. 허용되는 제어는 두 가지뿐

| 장치 | 가동 조건 | 정지 조건 | 제한 |
|---|---|---|---|
| **워터펌프** | 토양수분 < 하한 − **5%p** | 하한 회복 **또는** 최대 가동시간 도달 | 1회 최대 **5분**, 가동 사이 **30분** 휴지, 하루 **6회** |
| **환기팬** | 온도 > 상한 **+2℃** | 온도 ≤ 상한 | 시간 제한 **없음** |

- 펌프에 상한을 거는 이유: 오프라인에서 센서가 고장 나면 **침수**가 가장 큰
  위험이다. 하루 6회 한도가 마지막 방벽이다. 이 한도는 **오프라인 급수만**
  센다 — 서버가 정상 판단으로 돌린 급수까지 세면, 서버가 죽은 뒤 정작 필요한
  비상 급수를 막게 된다. 반면 30분 휴지시간은 누가 돌렸든 지킨다.
- 팬에 시간 제한을 두지 않는 이유: 고온은 몇 시간이면 작물을 잃는다.

### 4. 조명은 오프라인에서 제어하지 않는다

광량 부족은 즉각적인 피해가 아니고, 끊긴 상태에서 켜 두면 전력만 쓴다.

### 5. 페일세이프

- **부팅 시 모든 릴레이는 OFF 에서 시작한다.** 핀을 출력으로 바꾸기 *전에*
  비활성 레벨을 써서 부팅 순간의 글리치까지 막는다.
- **센서 읽기가 실패하면 아무것도 하지 않는다.** 네 항목 중 하나라도 NaN 이면
  그 주기는 통째로 버린다 — 값이 없으면 동작도 없다. 단, *이미 돌고 있는*
  펌프의 최대 가동시간 검사는 계속한다.
- **워치독 타이머**(기본 30초)가 펌웨어가 멈춘 채 릴레이가 닫혀 있는 상태를
  막는다.

### 6. 복귀 보고

오프라인 동안 한 동작은 복귀 후 `POST /api/smartfarm/{id}/controls` 로 올린다.
`reason` 이 **`오프라인 안전 제어`** 로 시작하므로 대시보드에서 서버 판단과
구분된다. 보고에 실패하면 큐에 남겨 다음 복귀에 다시 시도한다 (최대 16건,
넘치면 오래된 것부터 버린다).

---

## 빌드

```bash
cd firmware
pio run                 # 빌드
pio run -t upload       # 보드에 굽기
pio device monitor      # 시리얼 로그 (115200)
```

[`platformio.ini`](platformio.ini) 는 플랫폼과 라이브러리 버전을 전부 고정한다.
몇 달 뒤에 받아도 같은 바이너리가 나온다.

| 라이브러리 | 용도 |
|---|---|
| `knolleary/PubSubClient@2.8` | MQTT |
| `bblanchon/ArduinoJson@7.2.0` | `sensor/data` · `control/command` JSON |
| `adafruit/DHT sensor library@1.4.6` | DHT22 온습도 |
| `claws/BH1750@1.3.0` | 조도 |

### 현장 설정

Wi-Fi·브로커·재배구역 id 는 `-D` 플래그로 넣는다. `platformio.ini` 의
`build_flags` 를 고치거나, 한 번만 쓸 값이면:

```bash
pio run -e esp32dev \
  --project-option="build_flags=-DSMARTFARM_ID=2 -DWIFI_SSID='\"논산1동\"' -DMQTT_HOST='\"192.168.0.10\"'"
```

### 비밀정보

Wi-Fi 비밀번호를 커밋하지 않으려면 `firmware/secrets.ini` 를 만들고
(`.gitignore` 에 이미 들어 있다), `platformio.ini` 맨 아래
`extra_configs = secrets.ini` 주석을 푼다.

```ini
; secrets.ini
[env:esp32dev]
build_flags =
    ${env:esp32dev.build_flags}
    -DWIFI_SSID='"우리집공유기"'
    -DWIFI_PASSWORD='"실제비밀번호"'
```

---

## 테스트

오프라인 안전 규칙은 **보드 없이** 검증된다. `lib/farmcontrol` 이 순수 C++ 이라
호스트에서 그대로 컴파일되기 때문이다.

```bash
./firmware/run_host_tests.sh     # c++ 하나면 된다
pio test -e native               # PlatformIO 로도 같은 파일을 돌린다 (22 케이스)
```

테스트 본체는 프레임워크 없는 평범한 `main()` 이다. 그래야 PlatformIO 가
없어도 컴파일러 하나로 돌아간다. `test/test_custom_runner.py` 가 그 출력을
PlatformIO 결과 표로 옮겨 주는 얇은 어댑터다.

테스트가 잡아 두는 것 ([test/test_offline_control](test/test_offline_control)):

- 부팅 시 모든 릴레이 OFF
- 서버가 살아 있는 동안 가드는 릴레이를 건드리지 않는다
- 링크 단절·서버 침묵 두 경로의 오프라인 판정
- 펌프의 5%p 조건 · 5분 상한 · 30분 휴지 · 하루 6회 한도
  (한도는 **오프라인 급수만** 센다 — 서버가 돌린 급수는 빼고)
- 환기팬의 +2℃ 가동 / 상한 복귀 정지 · 시간 제한 없음
- 센서 실패 시 무동작, 단 돌고 있는 펌프의 상한은 계속 적용
- 조명은 오프라인에서 손대지 않는다
- 복귀 시 자기가 켠 것만 끄고 서버가 켠 것은 그대로 둔다
- 복귀 보고 큐 (넘치면 오래된 것부터)
- `millis()` 49.7일 롤오버

---

## 실물 없이 돌려보기

보드가 없어도 전체 흐름을 볼 수 있다. `tools/sensor_sim.py` 가 ESP32 의
센서 쪽을 대신한다.

```bash
docker compose up --build                              # 브로커 + 서버
uv run tools/sensor_sim.py --smartfarm 1 --scenario heat_spike
```

`control/command` 로 나가는 명령은 다음으로 확인한다:

```bash
docker compose exec mosquitto mosquitto_sub -t 'control/command' -v
```

---

## 주요 파일

| 파일 | 내용 |
|---|---|
| [`src/main.cpp`](src/main.cpp) | 센서 읽기 · MQTT 발행/구독 · 릴레이 · 복귀 보고 |
| [`include/config.h`](include/config.h) | 핀 배치 · 주기 · 네트워크 · 오프라인 기본 기준값 |
| [`lib/farmcontrol/`](lib/farmcontrol) | 오프라인 안전 제어 (Arduino 비의존, 호스트 테스트 대상) |
| [`test/test_offline_control/`](test/test_offline_control) | 안전 규칙 회귀 테스트 |
| [`test/test_custom_runner.py`](test/test_custom_runner.py) | `pio test -e native` 결과 어댑터 |
| [`platformio.ini`](platformio.ini) | 버전 고정된 빌드 설정 |
