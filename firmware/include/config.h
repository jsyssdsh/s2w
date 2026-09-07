// ESP32 엣지 제어기 설정 (SPEC 6.2 / 7.2).
//
// 여기 있는 값은 전부 platformio.ini 의 build_flags 로 덮어쓸 수 있다.
// 비밀정보(Wi-Fi 비밀번호)를 저장소에 커밋하지 않으려면 `firmware/secrets.ini`
// 를 만들어 쓴다 — 자세한 것은 firmware/README.md.
//
// 배선표(센서 → 핀, 릴레이 → 핀)도 firmware/README.md 에 있다. 핀 번호를
// 바꾸려면 두 곳을 함께 고친다.

#pragma once

// --------------------------------------------------------------------------
// 신원 — 이 보드가 담당하는 재배구역
// --------------------------------------------------------------------------

#ifndef SMARTFARM_ID
#define SMARTFARM_ID 1
#endif

#ifndef DEVICE_NAME
#define DEVICE_NAME "farmflow-esp32"
#endif

// --------------------------------------------------------------------------
// 네트워크
// --------------------------------------------------------------------------

#ifndef WIFI_SSID
#define WIFI_SSID "farmflow"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "changeme"
#endif

//: Mosquitto 브로커. docker-compose.yml 의 mosquitto 서비스와 같은 포트다.
#ifndef MQTT_HOST
#define MQTT_HOST "192.168.0.10"
#endif

#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif

//: 익명 접속이면 빈 문자열. 브로커에 인증을 걸면 채운다.
#ifndef MQTT_USERNAME
#define MQTT_USERNAME ""
#endif

#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD ""
#endif

//: 오프라인 동작 보고용 REST 주소 (ARCHITECTURE 11.3-6). 비우면 보고를 건너뛴다.
#ifndef API_BASE_URL
#define API_BASE_URL "http://192.168.0.10:8000"
#endif

// docs/ARCHITECTURE.md 11.1 — 토픽 계약. 서버와 글자가 같아야 한다.
#define TOPIC_SENSOR_DATA "sensor/data"
#define TOPIC_CONTROL_COMMAND "control/command"

// --------------------------------------------------------------------------
// 주기
// --------------------------------------------------------------------------

//: 센서 측정·발행 간격. 오프라인 판정(3배 = 90초)의 기준이기도 하다.
#ifndef SAMPLE_INTERVAL_MS
#define SAMPLE_INTERVAL_MS 30000UL
#endif

//: Wi-Fi / MQTT 재접속 시도 간격.
#ifndef RECONNECT_INTERVAL_MS
#define RECONNECT_INTERVAL_MS 5000UL
#endif

//: 워치독. 루프가 이 시간 안에 한 번은 돌아야 한다 (ARCHITECTURE 11.3-5).
#ifndef WATCHDOG_TIMEOUT_S
#define WATCHDOG_TIMEOUT_S 30
#endif

// --------------------------------------------------------------------------
// 배선 — GPIO 번호. firmware/README.md 의 배선표와 짝이다.
// --------------------------------------------------------------------------

//: DHT22 온습도 센서 DATA.
#ifndef PIN_DHT
#define PIN_DHT 4
#endif

//: BH1750 조도 센서 (I2C).
#ifndef PIN_I2C_SDA
#define PIN_I2C_SDA 21
#endif
#ifndef PIN_I2C_SCL
#define PIN_I2C_SCL 22
#endif

//: 정전용량식 토양수분 센서 AOUT. ADC1 채널이라 Wi-Fi 와 같이 쓸 수 있다.
#ifndef PIN_SOIL_ADC
#define PIN_SOIL_ADC 34
#endif

//: 4채널 릴레이 모듈 IN1~IN3.
#ifndef PIN_RELAY_PUMP
#define PIN_RELAY_PUMP 26
#endif
#ifndef PIN_RELAY_FAN
#define PIN_RELAY_FAN 27
#endif
#ifndef PIN_RELAY_LIGHT
#define PIN_RELAY_LIGHT 25
#endif

//: 대부분의 저가 릴레이 모듈은 LOW 에서 접점이 닫힌다. 보드가 다르면 0 으로.
#ifndef RELAY_ACTIVE_LOW
#define RELAY_ACTIVE_LOW 1
#endif

//: 온보드 LED — 켜져 있으면 온라인, 깜빡이면 오프라인 안전 제어 중.
#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED 2
#endif

// --------------------------------------------------------------------------
// 토양수분 ADC 보정
//
// 정전용량식 센서는 "마를수록 높은 전압" 이다. 공기 중(=0%)과 물속(=100%)에서
// 읽은 원시값으로 선형 보정한다. 센서 개체마다 다르니 실물로 재서 넣는다.
// --------------------------------------------------------------------------

#ifndef SOIL_ADC_DRY
#define SOIL_ADC_DRY 3200
#endif

#ifndef SOIL_ADC_WET
#define SOIL_ADC_WET 1350
#endif

//: 한 번 측정할 때 평균낼 샘플 수 (ADC 잡음 완화).
#ifndef SOIL_ADC_SAMPLES
#define SOIL_ADC_SAMPLES 16
#endif

// --------------------------------------------------------------------------
// 조도 대체 경로
//
// BH1750 이 없으면 LDR 분압을 ADC 로 읽어 대략적인 lux 로 환산한다.
// USE_BH1750 을 0 으로 두면 PIN_LUX_ADC 를 쓴다.
// --------------------------------------------------------------------------

#ifndef USE_BH1750
#define USE_BH1750 1
#endif

#ifndef PIN_LUX_ADC
#define PIN_LUX_ADC 35
#endif

//: LDR 경로에서 ADC 최대치(4095)가 몇 lx 에 해당하는지.
#ifndef LUX_ADC_FULL_SCALE
#define LUX_ADC_FULL_SCALE 40000.0f
#endif

// --------------------------------------------------------------------------
// 오프라인 안전 기준 — 서버 사본이 없을 때 쓰는 컴파일 상수.
// SPEC 5.5 의 토마토 기준이다 (ARCHITECTURE 11.3-2).
// --------------------------------------------------------------------------

#ifndef FALLBACK_TEMP_MIN
#define FALLBACK_TEMP_MIN 22.0f
#endif
#ifndef FALLBACK_TEMP_MAX
#define FALLBACK_TEMP_MAX 27.0f
#endif
#ifndef FALLBACK_HUMIDITY_MIN
#define FALLBACK_HUMIDITY_MIN 60.0f
#endif
#ifndef FALLBACK_HUMIDITY_MAX
#define FALLBACK_HUMIDITY_MAX 75.0f
#endif
#ifndef FALLBACK_SOIL_MIN
#define FALLBACK_SOIL_MIN 35.0f
#endif
#ifndef FALLBACK_SOIL_MAX
#define FALLBACK_SOIL_MAX 55.0f
#endif
#ifndef FALLBACK_LUX_MIN
#define FALLBACK_LUX_MIN 15000.0f
#endif

//: NVS 네임스페이스 — 기준값 사본이 재부팅을 넘어 살아남는 곳.
#define NVS_NAMESPACE "farmflow"
