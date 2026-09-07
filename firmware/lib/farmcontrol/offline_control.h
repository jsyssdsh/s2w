// 오프라인 안전 제어 — SPEC 6 "인터넷 연결이 끊겨도 설정된 안전 기준에 따라
// 펌프 및 환기장치를 제한적으로 제어한다".
//
// 이 파일에는 Arduino 의존성이 **하나도 없다.** 순수 C++ 이라 ESP32 에서도,
// 호스트 PC 에서도 똑같이 컴파일된다. 안전 규칙이 실물 없이 테스트되는 이유다
// (firmware/test/test_offline_control, firmware/run_host_tests.sh).
//
// 규칙의 출처는 docs/ARCHITECTURE.md 11.3 절이며, 요약은 firmware/README.md 에
// 있다. 서버가 살아 있는 동안에는 이 클래스가 릴레이를 건드리지 않는다 —
// 판단은 전부 서버가 하고(ARCHITECTURE 11절), 여기는 연결이 끊긴 동안만
// 작물을 살리기 위한 최소한의 동작을 한다.

#pragma once

#include <stddef.h>
#include <stdint.h>

namespace farmcontrol {

/// 서버 ``crop_thresholds`` 의 사본. 기본값은 SPEC 5.5 의 토마토 기준이다.
struct Thresholds {
  float temp_min = 22.0f;
  float temp_max = 27.0f;
  float humidity_min = 60.0f;
  float humidity_max = 75.0f;
  float soil_moisture_min = 35.0f;
  float soil_moisture_max = 55.0f;
  float lux_min = 15000.0f;
};

/// 센서 한 주기의 측정값. ``valid == false`` 면 읽기에 실패한 것이다.
struct Reading {
  bool valid = false;
  float temp_c = 0.0f;
  float humidity_pct = 0.0f;
  float lux = 0.0f;
  float soil_moisture_pct = 0.0f;
};

/// 릴레이가 물린 구동장치. 값은 서버 ``ControlDevice`` 와 1:1 대응한다.
enum class Relay : uint8_t { Pump = 0, Fan = 1, Light = 2 };

enum class Action : uint8_t { Off = 0, On = 1 };

constexpr uint8_t kRelayCount = 3;

/// 서버 ``control_events.device`` 문자열 ("pump" / "fan" / "light").
const char *relayName(Relay relay);
/// 서버 ``control_events.action`` 문자열 ("on" / "off").
const char *actionName(Action action);
/// 문자열 → 릴레이. 모르는 이름이면 false.
bool relayFromName(const char *name, Relay *out);

/// 오프라인 제어의 보수적 한계값. 전부 ARCHITECTURE 11.3 에서 왔다.
struct Limits {
  /// 마지막 ``control/command`` 이후 이만큼 지나면 오프라인으로 본다
  /// (측정 주기 30초의 3배).
  uint32_t offline_after_ms = 90UL * 1000UL;

  /// 펌프는 하한보다 이만큼(%p) 더 낮을 때만 돈다. 센서 고장 시 침수 방지.
  float pump_deficit_pct = 5.0f;
  /// 한 번에 최대 가동시간.
  uint32_t pump_max_on_ms = 5UL * 60UL * 1000UL;
  /// 가동 사이 최소 휴지시간.
  uint32_t pump_min_off_ms = 30UL * 60UL * 1000UL;
  /// 24시간 최대 가동 횟수.
  uint8_t pump_max_runs_per_day = 6;
  /// "하루" 의 길이. 테스트에서 줄여 쓴다.
  uint32_t day_ms = 24UL * 60UL * 60UL * 1000UL;

  /// 환기팬은 상한 + 이만큼(℃) 을 넘어야 돈다. 고온은 시간 제한을 두지 않는다.
  float fan_on_offset_c = 2.0f;
};

/// 오프라인 동안 실제로 한 동작. 복귀 후 서버에 보고한다 (ARCHITECTURE 11.3-6).
struct Event {
  Relay relay = Relay::Pump;
  Action action = Action::Off;
  uint32_t at_ms = 0;
  const char *reason = "";
};

constexpr uint8_t kMaxPendingEvents = 16;
constexpr uint8_t kPumpRunHistory = 12;

/// 오프라인 판정 + 펌프·환기팬의 제한적 제어.
///
/// 상태 기계는 통째로 여기 들어 있다. 호출자(``main.cpp``)가 하는 일은
/// ``update()`` 를 주기마다 부르고, ``relay()`` 가 돌려주는 상태를 GPIO 에
/// 반영하고, 복귀 후 ``pendingEvent()`` 를 서버로 보내는 것뿐이다.
class OfflineGuard {
 public:
  explicit OfflineGuard(const Limits &limits = Limits{});

  // -- 기준값 --------------------------------------------------------------

  /// NVS 사본이나 서버가 실어 보낸 값으로 기준을 갈아끼운다.
  void setThresholds(const Thresholds &thresholds, bool from_server);
  const Thresholds &thresholds() const { return thresholds_; }
  /// false 면 펌웨어 컴파일 상수를 쓰고 있다는 뜻이다.
  bool thresholdsFromServer() const { return thresholds_from_server_; }

  const Limits &limits() const { return limits_; }

  // -- 서버 쪽 사건 --------------------------------------------------------

  /// ``control/command`` 를 받았다. 오프라인 판정 시계를 되감는다.
  void noteServerCommand(uint32_t now_ms);
  /// 서버 명령으로 릴레이가 바뀌었다. 오프라인 판정이 상태를 잘못 알지 않도록
  /// 동기화한다.
  void noteServerRelay(Relay relay, Action action, uint32_t now_ms);

  // -- 주기 ----------------------------------------------------------------

  /// 브로커 연결이 끊겼거나, 마지막 명령 이후 ``offline_after_ms`` 가 지났는가.
  bool isOffline(uint32_t now_ms, bool link_up) const;

  /// 한 주기를 돌린다. 릴레이 상태가 바뀌었으면 true.
  ///
  /// 온라인이면 아무 판단도 하지 않는다 (복귀 직후 자기가 켠 것을 끄는 것만
  /// 예외). 오프라인이고 ``reading.valid`` 가 false 면 아무것도 하지 않는다 —
  /// 값이 없으면 동작도 없다 (ARCHITECTURE 11.3-5).
  bool update(uint32_t now_ms, bool link_up, const Reading &reading);

  Action relay(Relay relay) const { return relays_[static_cast<uint8_t>(relay)]; }
  bool offline() const { return offline_; }

  // -- 복귀 보고 큐 --------------------------------------------------------

  uint8_t pendingEvents() const { return pending_count_; }
  const Event &pendingEvent(uint8_t index) const { return pending_[index]; }
  void clearPendingEvents() { pending_count_ = 0; }

  /// 최근 24시간(``day_ms``) 안의 **오프라인** 펌프 가동 횟수.
  /// 서버가 내린 급수는 세지 않는다 — 한도는 오프라인 제어에 건 상한이다.
  uint8_t pumpRunsToday(uint32_t now_ms) const;

 private:
  void set(Relay relay, Action action, uint32_t now_ms, const char *reason, bool ours);
  void record(Relay relay, Action action, uint32_t now_ms, const char *reason);
  void updatePump(uint32_t now_ms, const Reading &reading, bool *changed);
  void updateFan(uint32_t now_ms, const Reading &reading, bool *changed);
  void releaseToServer(uint32_t now_ms, bool *changed);
  bool pumpRestSatisfied(uint32_t now_ms) const;

  Limits limits_;
  Thresholds thresholds_;
  bool thresholds_from_server_ = false;

  Action relays_[kRelayCount] = {Action::Off, Action::Off, Action::Off};
  /// 그 릴레이를 켠 것이 우리(오프라인 판단)인가. 복귀 시 이것만 끈다.
  bool ours_[kRelayCount] = {false, false, false};

  bool offline_ = false;
  bool have_server_command_ = false;
  uint32_t last_server_command_ms_ = 0;

  uint32_t pump_on_since_ms_ = 0;
  uint32_t pump_off_since_ms_ = 0;
  bool pump_has_run_ = false;

  uint32_t pump_runs_[kPumpRunHistory] = {0};
  uint8_t pump_run_count_ = 0;
  uint8_t pump_run_head_ = 0;

  Event pending_[kMaxPendingEvents];
  uint8_t pending_count_ = 0;
};

}  // namespace farmcontrol
