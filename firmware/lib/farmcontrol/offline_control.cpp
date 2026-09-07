#include "offline_control.h"

#include <string.h>

namespace farmcontrol {
namespace {

// millis() 는 약 49.7일마다 0으로 돌아간다. 부호 없는 뺄셈은 그 넘어감을
// 자연스럽게 흡수하므로, 시간 비교는 **반드시** 이 헬퍼를 거친다.
inline uint32_t elapsed(uint32_t now_ms, uint32_t since_ms) {
  return now_ms - since_ms;
}

}  // namespace

const char *relayName(Relay relay) {
  switch (relay) {
    case Relay::Pump:
      return "pump";
    case Relay::Fan:
      return "fan";
    case Relay::Light:
      return "light";
  }
  return "";
}

const char *actionName(Action action) {
  return action == Action::On ? "on" : "off";
}

bool relayFromName(const char *name, Relay *out) {
  if (name == nullptr || out == nullptr) {
    return false;
  }
  if (strcmp(name, "pump") == 0) {
    *out = Relay::Pump;
    return true;
  }
  if (strcmp(name, "fan") == 0) {
    *out = Relay::Fan;
    return true;
  }
  if (strcmp(name, "light") == 0) {
    *out = Relay::Light;
    return true;
  }
  return false;
}

OfflineGuard::OfflineGuard(const Limits &limits) : limits_(limits) {}

void OfflineGuard::setThresholds(const Thresholds &thresholds, bool from_server) {
  thresholds_ = thresholds;
  // 한 번이라도 서버 값을 받았으면 그 사실은 지워지지 않는다. NVS 사본을
  // 다시 읽어 들이는 부팅에서도 "서버에서 온 값" 이라는 표시가 유지된다.
  thresholds_from_server_ = thresholds_from_server_ || from_server;
}

void OfflineGuard::noteServerCommand(uint32_t now_ms) {
  have_server_command_ = true;
  last_server_command_ms_ = now_ms;
}

void OfflineGuard::noteServerRelay(Relay relay, Action action, uint32_t now_ms) {
  set(relay, action, now_ms, "서버 명령", /*ours=*/false);
}

bool OfflineGuard::isOffline(uint32_t now_ms, bool link_up) const {
  if (!link_up) {
    return true;
  }
  // 링크는 살아 있는데 서버가 조용하다 — 브로커나 서버 쪽이 죽은 경우다.
  // 아직 한 번도 명령을 받은 적이 없으면 온라인으로 본다: 갓 부팅했고
  // 적정 범위 안이라 서버가 보낼 명령이 없는 것이 정상이기 때문이다.
  if (!have_server_command_) {
    return false;
  }
  return elapsed(now_ms, last_server_command_ms_) >= limits_.offline_after_ms;
}

bool OfflineGuard::update(uint32_t now_ms, bool link_up, const Reading &reading) {
  const bool offline_now = isOffline(now_ms, link_up);
  bool changed = false;

  if (!offline_now) {
    if (offline_) {
      offline_ = false;
      releaseToServer(now_ms, &changed);
    }
    return changed;
  }

  offline_ = true;

  // 값이 없으면 동작도 없다 (ARCHITECTURE 11.3-5). 이미 돌고 있는 펌프는
  // 최대 가동시간 검사만 남기고 나머지 판단을 멈춘다.
  if (!reading.valid) {
    if (relays_[static_cast<uint8_t>(Relay::Pump)] == Action::On &&
        elapsed(now_ms, pump_on_since_ms_) >= limits_.pump_max_on_ms) {
      set(Relay::Pump, Action::Off, now_ms,
          "오프라인 안전 제어 — 센서 읽기 실패, 최대 가동시간 도달로 급수 중지", true);
      changed = true;
    }
    return changed;
  }

  updatePump(now_ms, reading, &changed);
  updateFan(now_ms, reading, &changed);
  // 조명은 오프라인에서 제어하지 않는다 (ARCHITECTURE 11.3-4).
  return changed;
}

void OfflineGuard::releaseToServer(uint32_t now_ms, bool *changed) {
  // 복귀 즉시 판단 권한을 서버에 돌려준다. 우리가 켠 것만 끈다 — 서버가 켜
  // 둔 장치를 임의로 끄면 그쪽 상태 기계와 어긋난다.
  for (uint8_t i = 0; i < kRelayCount; ++i) {
    if (relays_[i] == Action::On && ours_[i]) {
      set(static_cast<Relay>(i), Action::Off, now_ms,
          "오프라인 안전 제어 — 서버 복귀, 판단 권한 반환", true);
      *changed = true;
    }
    ours_[i] = false;
  }
}

bool OfflineGuard::pumpRestSatisfied(uint32_t now_ms) const {
  if (!pump_has_run_) {
    return true;  // 첫 가동은 기다릴 것이 없다.
  }
  return elapsed(now_ms, pump_off_since_ms_) >= limits_.pump_min_off_ms;
}

void OfflineGuard::updatePump(uint32_t now_ms, const Reading &reading, bool *changed) {
  const bool on = relays_[static_cast<uint8_t>(Relay::Pump)] == Action::On;
  const float start_below = thresholds_.soil_moisture_min - limits_.pump_deficit_pct;

  if (on) {
    if (elapsed(now_ms, pump_on_since_ms_) >= limits_.pump_max_on_ms) {
      set(Relay::Pump, Action::Off, now_ms,
          "오프라인 안전 제어 — 최대 가동시간 도달, 급수 중지", true);
      *changed = true;
      return;
    }
    if (reading.soil_moisture_pct >= thresholds_.soil_moisture_min) {
      set(Relay::Pump, Action::Off, now_ms,
          "오프라인 안전 제어 — 적정 수준 회복, 급수 중지", true);
      *changed = true;
    }
    return;
  }

  if (reading.soil_moisture_pct >= start_below) {
    return;  // 하한보다 5%p 이상 낮을 때만 손댄다.
  }
  if (!pumpRestSatisfied(now_ms)) {
    return;
  }
  if (pumpRunsToday(now_ms) >= limits_.pump_max_runs_per_day) {
    return;  // 하루 한도 — 센서 고장 시 침수를 막는 마지막 방벽.
  }

  set(Relay::Pump, Action::On, now_ms,
      "오프라인 안전 제어 — 토양수분 하한 미달, 제한 급수", true);
  *changed = true;
}

void OfflineGuard::updateFan(uint32_t now_ms, const Reading &reading, bool *changed) {
  const bool on = relays_[static_cast<uint8_t>(Relay::Fan)] == Action::On;
  const float start_above = thresholds_.temp_max + limits_.fan_on_offset_c;

  if (!on && reading.temp_c > start_above) {
    // 고온은 몇 시간이면 작물을 잃는다 — 시간 제한을 두지 않는다.
    set(Relay::Fan, Action::On, now_ms,
        "오프라인 안전 제어 — 온도 상한 초과, 환기 가동", true);
    *changed = true;
    return;
  }
  if (on && reading.temp_c <= thresholds_.temp_max) {
    set(Relay::Fan, Action::Off, now_ms,
        "오프라인 안전 제어 — 온도 적정 범위 복귀, 환기 중지", true);
    *changed = true;
  }
}

void OfflineGuard::set(Relay relay, Action action, uint32_t now_ms, const char *reason,
                       bool ours) {
  const uint8_t index = static_cast<uint8_t>(relay);
  if (relays_[index] == action) {
    if (!ours) {
      ours_[index] = false;  // 서버가 재확인한 상태는 더 이상 우리 것이 아니다.
    }
    return;
  }

  relays_[index] = action;
  ours_[index] = ours && action == Action::On;

  if (relay == Relay::Pump) {
    if (action == Action::On) {
      pump_on_since_ms_ = now_ms;
      pump_has_run_ = true;
      if (ours) {
        // 하루 6회 한도는 **오프라인 제어**에 걸린 상한이다. 서버가 정상
        // 판단으로 급수한 횟수까지 세면, 서버가 죽은 뒤 정작 필요한 비상
        // 급수를 막게 된다. 반대로 최소 휴지시간은 누가 돌렸든 지킨다 —
        // 그쪽은 토양과 펌프의 사정이지 판단 주체의 문제가 아니다.
        pump_runs_[pump_run_head_] = now_ms;
        pump_run_head_ = static_cast<uint8_t>((pump_run_head_ + 1) % kPumpRunHistory);
        if (pump_run_count_ < kPumpRunHistory) {
          ++pump_run_count_;
        }
      }
    } else {
      pump_off_since_ms_ = now_ms;
    }
  }

  if (ours) {
    record(relay, action, now_ms, reason);
  }
}

void OfflineGuard::record(Relay relay, Action action, uint32_t now_ms,
                          const char *reason) {
  if (pending_count_ >= kMaxPendingEvents) {
    // 큐가 넘치면 가장 오래된 것을 버린다. 최근 이력이 더 쓸모 있다.
    for (uint8_t i = 1; i < kMaxPendingEvents; ++i) {
      pending_[i - 1] = pending_[i];
    }
    pending_count_ = kMaxPendingEvents - 1;
  }
  Event &event = pending_[pending_count_++];
  event.relay = relay;
  event.action = action;
  event.at_ms = now_ms;
  event.reason = reason;
}

uint8_t OfflineGuard::pumpRunsToday(uint32_t now_ms) const {
  uint8_t count = 0;
  for (uint8_t i = 0; i < pump_run_count_; ++i) {
    if (elapsed(now_ms, pump_runs_[i]) < limits_.day_ms) {
      ++count;
    }
  }
  return count;
}

}  // namespace farmcontrol
