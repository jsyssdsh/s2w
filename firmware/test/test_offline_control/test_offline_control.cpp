// 오프라인 안전 제어 호스트 테스트 (SPEC 6 / ARCHITECTURE 11.3).
//
// Arduino 도, ESP32 도, 실물 센서도 필요 없다. 두 가지 방법으로 돌린다:
//
//   ./firmware/run_host_tests.sh          # c++ 하나로 컴파일해서 실행
//   pio test -e native                    # PlatformIO 의 native 환경
//
// 프레임워크를 쓰지 않는 이유는 두 경로가 같은 파일을 쓰게 하려는 것이다
// (platformio.ini 의 test_framework = custom).

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "offline_control.h"

using farmcontrol::Action;
using farmcontrol::Limits;
using farmcontrol::OfflineGuard;
using farmcontrol::Reading;
using farmcontrol::Relay;
using farmcontrol::Thresholds;

namespace {

int g_failures = 0;
int g_checks = 0;
const char *g_current = "";

void check(bool ok, const char *expr, int line) {
  ++g_checks;
  if (!ok) {
    ++g_failures;
    std::printf("  FAIL %s:%d  %s\n", g_current, line, expr);
  }
}

#define CHECK(expr) check((expr), #expr, __LINE__)

void begin(const char *name) {
  g_current = name;
  std::printf("- %s\n", name);
}

constexpr uint32_t kMinute = 60UL * 1000UL;
constexpr uint32_t kSecond = 1000UL;

// SPEC 5.5 토마토 기준: 22~27℃ / 60~75% / 토양수분 35~55%.
Thresholds tomato() { return Thresholds{}; }

Reading ok(float temp, float soil) {
  Reading reading;
  reading.valid = true;
  reading.temp_c = temp;
  reading.humidity_pct = 68.0f;
  reading.lux = 18000.0f;
  reading.soil_moisture_pct = soil;
  return reading;
}

/// 서버와 연결된 상태로 만들어 둔 가드. 이후 link_up=false 를 주면 오프라인이다.
OfflineGuard online(const Limits &limits = Limits{}) {
  OfflineGuard guard(limits);
  guard.setThresholds(tomato(), /*from_server=*/false);
  guard.noteServerCommand(0);
  return guard;
}

// --------------------------------------------------------------------------

void test_boots_with_every_relay_off() {
  begin("부팅 시 모든 릴레이가 OFF 다");
  OfflineGuard guard;
  CHECK(guard.relay(Relay::Pump) == Action::Off);
  CHECK(guard.relay(Relay::Fan) == Action::Off);
  CHECK(guard.relay(Relay::Light) == Action::Off);
  CHECK(!guard.offline());
  CHECK(!guard.thresholdsFromServer());
}

void test_online_guard_never_touches_relays() {
  begin("서버가 살아 있으면 가드는 릴레이를 건드리지 않는다");
  OfflineGuard guard = online();
  // 서버라면 진작 환기·급수를 시켰을 값인데도 아무 일도 없어야 한다.
  for (uint32_t t = kSecond; t <= 60 * kSecond; t += kSecond) {
    guard.noteServerCommand(t);
    guard.update(t, /*link_up=*/true, ok(35.0f, 10.0f));
  }
  CHECK(guard.relay(Relay::Fan) == Action::Off);
  CHECK(guard.relay(Relay::Pump) == Action::Off);
  CHECK(guard.pendingEvents() == 0);
}

void test_link_loss_enters_offline_mode() {
  begin("링크가 끊기면 즉시 오프라인이다");
  OfflineGuard guard = online();
  CHECK(!guard.isOffline(kSecond, /*link_up=*/true));
  CHECK(guard.isOffline(kSecond, /*link_up=*/false));
}

void test_server_silence_enters_offline_mode() {
  begin("링크는 살아 있어도 명령이 90초 끊기면 오프라인이다");
  Limits limits;
  OfflineGuard guard = online(limits);
  CHECK(!guard.isOffline(limits.offline_after_ms - 1, true));
  CHECK(guard.isOffline(limits.offline_after_ms, true));
}

void test_fresh_boot_is_not_offline_without_commands() {
  begin("명령을 한 번도 못 받은 갓 부팅 상태는 오프라인이 아니다");
  OfflineGuard guard;  // noteServerCommand 없음
  CHECK(!guard.isOffline(10 * kMinute, /*link_up=*/true));
  CHECK(guard.isOffline(10 * kMinute, /*link_up=*/false));
}

void test_fan_runs_only_above_the_offset() {
  begin("환기팬은 상한 +2℃ 를 넘어야 돌고, 상한 아래로 오면 멈춘다");
  OfflineGuard guard = online();

  // 27.0 + 2.0 = 29.0 이하는 손대지 않는다.
  guard.update(kMinute, false, ok(29.0f, 45.0f));
  CHECK(guard.relay(Relay::Fan) == Action::Off);

  guard.update(2 * kMinute, false, ok(29.1f, 45.0f));
  CHECK(guard.relay(Relay::Fan) == Action::On);

  // 27.1℃ 는 아직 상한 위 — 계속 돈다 (히스테리시스).
  guard.update(3 * kMinute, false, ok(27.1f, 45.0f));
  CHECK(guard.relay(Relay::Fan) == Action::On);

  guard.update(4 * kMinute, false, ok(27.0f, 45.0f));
  CHECK(guard.relay(Relay::Fan) == Action::Off);
}

void test_fan_has_no_time_limit() {
  begin("고온에서는 환기팬에 시간 제한이 없다");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(33.0f, 45.0f));
  CHECK(guard.relay(Relay::Fan) == Action::On);
  for (uint32_t t = 2; t <= 6 * 60; ++t) {  // 6시간
    guard.update(t * kMinute, false, ok(33.0f, 45.0f));
  }
  CHECK(guard.relay(Relay::Fan) == Action::On);
}

void test_pump_needs_a_five_point_deficit() {
  begin("펌프는 하한보다 5%p 이상 낮아야 돈다");
  OfflineGuard guard = online();

  // 하한 35% − 5%p = 30%. 30.0 은 아직 아니다.
  guard.update(kMinute, false, ok(24.0f, 30.0f));
  CHECK(guard.relay(Relay::Pump) == Action::Off);

  guard.update(2 * kMinute, false, ok(24.0f, 29.9f));
  CHECK(guard.relay(Relay::Pump) == Action::On);
}

void test_pump_stops_at_the_maximum_on_time() {
  begin("펌프는 최대 5분 뒤 반드시 멈춘다 (센서가 계속 낮아도)");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);

  guard.update(kMinute + 5 * kMinute - kSecond, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);

  guard.update(kMinute + 5 * kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::Off);
}

void test_pump_stops_when_soil_recovers() {
  begin("적정 수준을 회복하면 최대 가동시간 전에도 멈춘다");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);
  guard.update(2 * kMinute, false, ok(24.0f, 35.0f));
  CHECK(guard.relay(Relay::Pump) == Action::Off);
}

void test_pump_rests_thirty_minutes() {
  begin("펌프는 가동 사이 30분을 쉰다");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(24.0f, 20.0f));
  guard.update(6 * kMinute, false, ok(24.0f, 20.0f));  // 최대 가동시간으로 정지
  CHECK(guard.relay(Relay::Pump) == Action::Off);

  guard.update(6 * kMinute + 29 * kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::Off);

  guard.update(6 * kMinute + 30 * kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);
}

void test_pump_daily_quota_caps_flooding() {
  begin("펌프는 하루 6회를 넘기지 않는다 — 센서가 고장 나도");
  OfflineGuard guard = online();

  uint32_t t = kMinute;
  for (int run = 0; run < 10; ++run) {
    guard.update(t, false, ok(24.0f, 5.0f));  // 켜기 시도
    t += 5 * kMinute;
    guard.update(t, false, ok(24.0f, 5.0f));  // 최대 가동시간 → 정지
    t += 30 * kMinute;                        // 휴지시간 소진
  }
  CHECK(guard.pumpRunsToday(t) == 6);
  CHECK(guard.relay(Relay::Pump) == Action::Off);

  // 24시간이 지나면 한도가 풀린다.
  uint32_t next_day = t + 24UL * 60UL * kMinute;
  CHECK(guard.pumpRunsToday(next_day) == 0);
  guard.update(next_day, false, ok(24.0f, 5.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);
}

void test_daily_quota_ignores_server_driven_watering() {
  begin("하루 한도는 오프라인 급수만 센다 — 서버가 돌린 급수는 빼고");
  OfflineGuard guard = online();

  uint32_t t = kMinute;
  for (int run = 0; run < 8; ++run) {
    guard.noteServerRelay(Relay::Pump, Action::On, t);
    t += 5 * kMinute;
    guard.noteServerRelay(Relay::Pump, Action::Off, t);
    t += 30 * kMinute;
    guard.noteServerCommand(t);
  }
  CHECK(guard.pumpRunsToday(t) == 0);

  // 서버가 죽었다. 한도를 다 쓰지 않았으니 비상 급수가 가능해야 한다.
  guard.update(t + 2 * kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);
  CHECK(guard.pumpRunsToday(t + 2 * kMinute) == 1);
}

void test_invalid_reading_does_nothing() {
  begin("센서 읽기가 실패하면 아무것도 하지 않는다");
  OfflineGuard guard = online();
  Reading broken;  // valid == false
  guard.update(kMinute, false, broken);
  CHECK(guard.relay(Relay::Pump) == Action::Off);
  CHECK(guard.relay(Relay::Fan) == Action::Off);
  CHECK(guard.pendingEvents() == 0);
}

void test_invalid_reading_still_enforces_the_pump_limit() {
  begin("센서가 죽어도 돌고 있던 펌프는 최대 가동시간에 멈춘다");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);

  Reading broken;
  guard.update(kMinute + 5 * kMinute, false, broken);
  CHECK(guard.relay(Relay::Pump) == Action::Off);
}

void test_light_is_never_controlled_offline() {
  begin("조명은 오프라인에서 제어하지 않는다");
  OfflineGuard guard = online();
  Reading dark = ok(24.0f, 45.0f);
  dark.lux = 0.0f;
  for (uint32_t t = kMinute; t <= 120 * kMinute; t += kMinute) {
    guard.update(t, false, dark);
  }
  CHECK(guard.relay(Relay::Light) == Action::Off);
}

void test_reconnect_returns_authority_to_the_server() {
  begin("복귀하면 오프라인 동안 켠 것을 끄고 판단 권한을 서버에 돌려준다");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(33.0f, 20.0f));
  CHECK(guard.relay(Relay::Fan) == Action::On);
  CHECK(guard.relay(Relay::Pump) == Action::On);
  CHECK(guard.offline());

  guard.noteServerCommand(2 * kMinute);
  const bool changed = guard.update(2 * kMinute, true, ok(33.0f, 20.0f));
  CHECK(changed);
  CHECK(!guard.offline());
  CHECK(guard.relay(Relay::Fan) == Action::Off);
  CHECK(guard.relay(Relay::Pump) == Action::Off);
}

void test_reconnect_leaves_server_driven_relays_alone() {
  begin("서버가 켜 둔 릴레이는 복귀 시 건드리지 않는다");
  OfflineGuard guard = online();
  guard.noteServerRelay(Relay::Light, Action::On, kSecond);
  guard.update(kMinute, false, ok(24.0f, 45.0f));  // 오프라인이지만 할 일 없음

  guard.noteServerCommand(2 * kMinute);
  guard.update(2 * kMinute, true, ok(24.0f, 45.0f));
  CHECK(guard.relay(Relay::Light) == Action::On);
}

void test_offline_actions_are_queued_for_reporting() {
  begin("오프라인 동작은 복귀 후 보고하려고 큐에 쌓인다");
  OfflineGuard guard = online();
  guard.update(kMinute, false, ok(33.0f, 20.0f));
  CHECK(guard.pendingEvents() == 2);
  CHECK(guard.pendingEvent(0).relay == Relay::Pump);
  CHECK(guard.pendingEvent(0).action == Action::On);
  CHECK(std::strstr(guard.pendingEvent(0).reason, "오프라인 안전 제어") != nullptr);
  CHECK(guard.pendingEvent(1).relay == Relay::Fan);

  guard.clearPendingEvents();
  CHECK(guard.pendingEvents() == 0);
}

void test_report_queue_drops_the_oldest_when_full() {
  begin("보고 큐가 넘치면 가장 오래된 것부터 버린다");
  OfflineGuard guard = online();
  uint32_t t = kMinute;
  for (int i = 0; i < 20; ++i) {
    guard.update(t, false, ok(33.0f, 45.0f));      // 환기 가동
    t += kMinute;
    guard.update(t, false, ok(24.0f, 45.0f));      // 환기 중지
    t += kMinute;
  }
  CHECK(guard.pendingEvents() == farmcontrol::kMaxPendingEvents);
}

void test_server_thresholds_replace_the_compiled_defaults() {
  begin("서버 기준값이 오면 컴파일 상수를 대체한다");
  OfflineGuard guard = online();
  Thresholds strawberry;  // SPEC 시드의 딸기 기준
  strawberry.temp_max = 25.0f;
  strawberry.soil_moisture_min = 40.0f;
  guard.setThresholds(strawberry, /*from_server=*/true);
  CHECK(guard.thresholdsFromServer());

  // 27.1℃ 는 토마토 기준이면 아무 일도 없지만, 딸기 기준(25+2=27)에서는 환기다.
  guard.update(kMinute, false, ok(27.1f, 45.0f));
  CHECK(guard.relay(Relay::Fan) == Action::On);
}

void test_millis_rollover_is_handled() {
  begin("millis() 가 0으로 되돌아가도 시간 계산이 깨지지 않는다");
  OfflineGuard guard(Limits{});
  guard.setThresholds(tomato(), false);

  const uint32_t near_max = 0xFFFFFFFFUL - 2 * kMinute;
  guard.noteServerCommand(near_max);
  guard.update(near_max, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::On);

  // 넘어간 뒤 5분째 — 부호 없는 뺄셈이 그대로 5분을 돌려줘야 한다.
  const uint32_t after = near_max + 5 * kMinute;  // 자연 오버플로
  guard.update(after, false, ok(24.0f, 20.0f));
  CHECK(guard.relay(Relay::Pump) == Action::Off);
}

void test_relay_names_match_the_server_contract() {
  begin("릴레이 이름이 서버 ControlDevice 값과 같다");
  CHECK(std::strcmp(farmcontrol::relayName(Relay::Pump), "pump") == 0);
  CHECK(std::strcmp(farmcontrol::relayName(Relay::Fan), "fan") == 0);
  CHECK(std::strcmp(farmcontrol::relayName(Relay::Light), "light") == 0);
  CHECK(std::strcmp(farmcontrol::actionName(Action::On), "on") == 0);
  CHECK(std::strcmp(farmcontrol::actionName(Action::Off), "off") == 0);

  Relay parsed = Relay::Light;
  CHECK(farmcontrol::relayFromName("fan", &parsed) && parsed == Relay::Fan);
  CHECK(!farmcontrol::relayFromName("heater", &parsed));
}

}  // namespace

int main() {
  std::printf("오프라인 안전 제어 테스트 (ARCHITECTURE 11.3)\n");

  test_boots_with_every_relay_off();
  test_online_guard_never_touches_relays();
  test_link_loss_enters_offline_mode();
  test_server_silence_enters_offline_mode();
  test_fresh_boot_is_not_offline_without_commands();
  test_fan_runs_only_above_the_offset();
  test_fan_has_no_time_limit();
  test_pump_needs_a_five_point_deficit();
  test_pump_stops_at_the_maximum_on_time();
  test_pump_stops_when_soil_recovers();
  test_pump_rests_thirty_minutes();
  test_pump_daily_quota_caps_flooding();
  test_daily_quota_ignores_server_driven_watering();
  test_invalid_reading_does_nothing();
  test_invalid_reading_still_enforces_the_pump_limit();
  test_light_is_never_controlled_offline();
  test_reconnect_returns_authority_to_the_server();
  test_reconnect_leaves_server_driven_relays_alone();
  test_offline_actions_are_queued_for_reporting();
  test_report_queue_drops_the_oldest_when_full();
  test_server_thresholds_replace_the_compiled_defaults();
  test_millis_rollover_is_handled();
  test_relay_names_match_the_server_contract();

  std::printf("\n%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
