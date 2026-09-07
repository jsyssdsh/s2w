// ESP32 엣지 제어기 — 센서 → MQTT → 서버, 서버 → MQTT → 릴레이 (SPEC 6 / 7.2).
//
// 이 파일이 하는 일은 딱 네 가지다:
//
//   1. 온습도·조도·토양수분을 SAMPLE_INTERVAL_MS 마다 읽어
//      ``sensor/data`` 로 발행한다.
//   2. ``control/command`` 를 구독해 워터펌프 / 환기팬 / 조명 릴레이를 민다.
//   3. 연결이 끊기면 farmcontrol::OfflineGuard 에 판단을 넘긴다 —
//      보수적이고 시간 제한이 걸린 오프라인 안전 제어 (ARCHITECTURE 11.3).
//   4. 복귀하면 오프라인 동안 한 동작을 서버에 보고한다.
//
// **판단 로직은 여기 없다.** 기준값과 히스테리시스는 서버 한 곳
// (backend/app/services/smartfarm.py) 에만 있고, 펌웨어는 그것을 복제하지
// 않는다. 오프라인 안전 규칙만이 예외이며, 그마저도 lib/farmcontrol 로
// 분리해 호스트에서 테스트한다 (firmware/run_host_tests.sh).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#include <DHT.h>

// config.h 가 USE_BH1750 을 정의한다. 조건부 include 보다 **먼저** 와야 한다 —
// 순서가 뒤집히면 매크로가 없는 상태로 #if 가 평가돼 헤더만 조용히 빠진다.
#include "config.h"
#include "offline_control.h"

#if USE_BH1750
#include <BH1750.h>
#endif

using farmcontrol::Action;
using farmcontrol::OfflineGuard;
using farmcontrol::Reading;
using farmcontrol::Relay;
using farmcontrol::Thresholds;

namespace {

WiFiClient g_net;
PubSubClient g_mqtt(g_net);
DHT g_dht(PIN_DHT, DHT22);
#if USE_BH1750
BH1750 g_lightMeter;
bool g_lightMeterReady = false;
#endif
Preferences g_prefs;
OfflineGuard g_guard;

uint32_t g_lastSampleMs = 0;
uint32_t g_lastReconnectMs = 0;

const uint8_t kRelayPins[farmcontrol::kRelayCount] = {
    PIN_RELAY_PUMP,  // Relay::Pump
    PIN_RELAY_FAN,   // Relay::Fan
    PIN_RELAY_LIGHT  // Relay::Light
};

// --------------------------------------------------------------------------
// 릴레이
// --------------------------------------------------------------------------

void writeRelay(Relay relay, Action action) {
  const uint8_t pin = kRelayPins[static_cast<uint8_t>(relay)];
  const bool energised = (action == Action::On);
#if RELAY_ACTIVE_LOW
  digitalWrite(pin, energised ? LOW : HIGH);
#else
  digitalWrite(pin, energised ? HIGH : LOW);
#endif
}

/// 가드가 들고 있는 상태를 그대로 GPIO 에 반영한다. 릴레이의 진실은 하나뿐이다.
void syncRelays() {
  for (uint8_t i = 0; i < farmcontrol::kRelayCount; ++i) {
    const Relay relay = static_cast<Relay>(i);
    writeRelay(relay, g_guard.relay(relay));
  }
}

// --------------------------------------------------------------------------
// NVS — 기준값 사본 (ARCHITECTURE 11.3-2)
// --------------------------------------------------------------------------

Thresholds compiledFallback() {
  Thresholds t;
  t.temp_min = FALLBACK_TEMP_MIN;
  t.temp_max = FALLBACK_TEMP_MAX;
  t.humidity_min = FALLBACK_HUMIDITY_MIN;
  t.humidity_max = FALLBACK_HUMIDITY_MAX;
  t.soil_moisture_min = FALLBACK_SOIL_MIN;
  t.soil_moisture_max = FALLBACK_SOIL_MAX;
  t.lux_min = FALLBACK_LUX_MIN;
  return t;
}

void loadThresholds() {
  Thresholds t = compiledFallback();
  g_prefs.begin(NVS_NAMESPACE, /*readOnly=*/true);
  const bool stored = g_prefs.getBool("th_ok", false);
  if (stored) {
    t.temp_min = g_prefs.getFloat("temp_min", t.temp_min);
    t.temp_max = g_prefs.getFloat("temp_max", t.temp_max);
    t.humidity_min = g_prefs.getFloat("hum_min", t.humidity_min);
    t.humidity_max = g_prefs.getFloat("hum_max", t.humidity_max);
    t.soil_moisture_min = g_prefs.getFloat("soil_min", t.soil_moisture_min);
    t.soil_moisture_max = g_prefs.getFloat("soil_max", t.soil_moisture_max);
    t.lux_min = g_prefs.getFloat("lux_min", t.lux_min);
  }
  g_prefs.end();

  g_guard.setThresholds(t, /*from_server=*/stored);
  Serial.printf("[cfg] 기준값 출처: %s (온도 %.1f~%.1f℃, 토양수분 %.1f%% 이상)\n",
                stored ? "NVS 사본" : "컴파일 상수", t.temp_min, t.temp_max,
                t.soil_moisture_min);
}

void saveThresholds(const Thresholds &t) {
  g_prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
  g_prefs.putFloat("temp_min", t.temp_min);
  g_prefs.putFloat("temp_max", t.temp_max);
  g_prefs.putFloat("hum_min", t.humidity_min);
  g_prefs.putFloat("hum_max", t.humidity_max);
  g_prefs.putFloat("soil_min", t.soil_moisture_min);
  g_prefs.putFloat("soil_max", t.soil_moisture_max);
  g_prefs.putFloat("lux_min", t.lux_min);
  g_prefs.putBool("th_ok", true);
  g_prefs.end();
}

// --------------------------------------------------------------------------
// 센서
// --------------------------------------------------------------------------

float readSoilMoisturePct() {
  uint32_t total = 0;
  for (int i = 0; i < SOIL_ADC_SAMPLES; ++i) {
    total += analogRead(PIN_SOIL_ADC);
    delay(2);
  }
  const float raw = static_cast<float>(total) / SOIL_ADC_SAMPLES;
  // 정전용량식 센서는 마를수록 값이 크다 — DRY 를 0%, WET 을 100% 로 잡는다.
  const float span = static_cast<float>(SOIL_ADC_DRY - SOIL_ADC_WET);
  if (span == 0.0f) {
    return NAN;
  }
  const float pct = (SOIL_ADC_DRY - raw) / span * 100.0f;
  return constrain(pct, 0.0f, 100.0f);
}

float readLux() {
#if USE_BH1750
  if (g_lightMeterReady) {
    const float lux = g_lightMeter.readLightLevel();
    if (lux >= 0.0f) {
      return lux;
    }
  }
  return NAN;
#else
  const float raw = static_cast<float>(analogRead(PIN_LUX_ADC));
  return raw / 4095.0f * LUX_ADC_FULL_SCALE;
#endif
}

/// 네 항목을 모두 읽는다. **하나라도 실패하면 valid=false** —
/// 값이 없으면 동작도 없다 (ARCHITECTURE 11.3-5).
Reading readSensors() {
  Reading reading;
  const float temp = g_dht.readTemperature();
  const float humidity = g_dht.readHumidity();
  const float lux = readLux();
  const float soil = readSoilMoisturePct();

  if (isnan(temp) || isnan(humidity) || isnan(lux) || isnan(soil)) {
    Serial.println("[sensor] 읽기 실패 — 이번 주기는 건너뛴다");
    return reading;
  }

  reading.valid = true;
  reading.temp_c = temp;
  reading.humidity_pct = humidity;
  reading.lux = lux;
  reading.soil_moisture_pct = soil;
  return reading;
}

// --------------------------------------------------------------------------
// MQTT
// --------------------------------------------------------------------------

/// ``sensor/data`` 발행. 필드 이름은 서버의 ``SensorReadingIn`` 그대로다
/// (ARCHITECTURE 11.1). ``ts`` 는 보내지 않는다 — 보드에 RTC 가 없으므로
/// 서버 수신 시각을 쓰게 두는 편이 정확하다.
bool publishReading(const Reading &reading) {
  JsonDocument doc;
  doc["smartfarm_id"] = SMARTFARM_ID;
  doc["temp_c"] = roundf(reading.temp_c * 10.0f) / 10.0f;
  doc["humidity_pct"] = roundf(reading.humidity_pct * 10.0f) / 10.0f;
  doc["lux"] = roundf(reading.lux);
  doc["soil_moisture_pct"] = roundf(reading.soil_moisture_pct * 10.0f) / 10.0f;

  char payload[192];
  const size_t written = serializeJson(doc, payload, sizeof(payload));
  if (written == 0) {
    return false;
  }
  // 서버 브리지가 qos=1 로 구독한다. PubSubClient 는 발행 QoS 0 만 지원하므로
  // 유실 감내는 다음 주기(30초)의 재전송에 맡긴다 — 센서값은 최신치가 중요하다.
  return g_mqtt.publish(TOPIC_SENSOR_DATA, payload);
}

/// ``control/command`` 수신 — 서버가 내린 명령을 릴레이에 그대로 옮긴다.
void onCommand(char *topic, byte *payload, unsigned int length) {
  (void)topic;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) {
    Serial.println("[mqtt] control/command 파싱 실패");
    return;
  }

  // 브로커는 모든 보드에 같은 토픽을 뿌린다. 내 재배구역인지 먼저 본다.
  const int target = doc["smartfarm_id"] | -1;
  if (target != SMARTFARM_ID) {
    return;
  }

  const uint32_t now = millis();
  // 명령이 왔다는 사실 자체가 "서버가 살아 있다" 는 증거다.
  g_guard.noteServerCommand(now);

  // 서버가 기준값을 실어 보내면 NVS 사본을 갱신한다. 지금 서버는 보내지
  // 않으므로 이 가지는 앞으로를 위한 것이다 (ARCHITECTURE 11.3-2).
  JsonObjectConst limits = doc["thresholds"];
  if (!limits.isNull()) {
    Thresholds t = g_guard.thresholds();
    t.temp_min = limits["temp_min"] | t.temp_min;
    t.temp_max = limits["temp_max"] | t.temp_max;
    t.humidity_min = limits["humidity_min"] | t.humidity_min;
    t.humidity_max = limits["humidity_max"] | t.humidity_max;
    t.soil_moisture_min = limits["soil_moisture_min"] | t.soil_moisture_min;
    t.soil_moisture_max = limits["soil_moisture_max"] | t.soil_moisture_max;
    t.lux_min = limits["lux_min"] | t.lux_min;
    g_guard.setThresholds(t, /*from_server=*/true);
    saveThresholds(t);
  }

  const char *device = doc["device"] | "";
  const char *action = doc["action"] | "";
  Relay relay;
  if (!farmcontrol::relayFromName(device, &relay)) {
    Serial.printf("[mqtt] 모르는 device: %s\n", device);
    return;
  }
  const Action wanted = (strcmp(action, "on") == 0) ? Action::On : Action::Off;

  g_guard.noteServerRelay(relay, wanted, now);
  writeRelay(relay, wanted);
  Serial.printf("[mqtt] 서버 명령: %s %s (%s)\n", device, action,
                doc["reason"] | "");
}

bool connectMqtt() {
  char clientId[48];
  snprintf(clientId, sizeof(clientId), "%s-%d-%06X", DEVICE_NAME, SMARTFARM_ID,
           static_cast<uint32_t>(ESP.getEfuseMac() & 0xFFFFFF));

  const bool ok = (strlen(MQTT_USERNAME) > 0)
                      ? g_mqtt.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)
                      : g_mqtt.connect(clientId);
  if (!ok) {
    Serial.printf("[mqtt] 접속 실패 (state=%d) — %lums 뒤 재시도\n", g_mqtt.state(),
                  RECONNECT_INTERVAL_MS);
    return false;
  }
  g_mqtt.subscribe(TOPIC_CONTROL_COMMAND, 1);
  Serial.printf("[mqtt] 접속됨 %s:%d, 구독 %s\n", MQTT_HOST, MQTT_PORT,
                TOPIC_CONTROL_COMMAND);
  return true;
}

// --------------------------------------------------------------------------
// 복귀 보고 (ARCHITECTURE 11.3-6)
// --------------------------------------------------------------------------

/// 오프라인 동안 한 동작을 ``POST /api/smartfarm/{id}/controls`` 로 올린다.
/// 그래야 서버의 ``control_events`` 가 실제 장치 이력과 어긋나지 않는다.
///
/// 온라인이기만 하면 매 주기에 불린다. 복귀 순간에 한 번만 부르면, 복귀
/// 처리가 만들어 내는 "판단 권한 반환" 정지 기록이 다음 단절 때까지 큐에
/// 남아 있게 된다.
void reportOfflineActions() {
  if (g_guard.pendingEvents() == 0) {
    return;
  }
  if (strlen(API_BASE_URL) == 0) {
    g_guard.clearPendingEvents();  // 보고할 곳이 없으면 쌓아 둘 이유도 없다.
    return;
  }

  char url[128];
  snprintf(url, sizeof(url), "%s/api/smartfarm/%d/controls", API_BASE_URL,
           SMARTFARM_ID);

  bool allSent = true;
  for (uint8_t i = 0; i < g_guard.pendingEvents(); ++i) {
    const farmcontrol::Event &event = g_guard.pendingEvent(i);

    JsonDocument doc;
    doc["device"] = farmcontrol::relayName(event.relay);
    doc["action"] = farmcontrol::actionName(event.action);
    doc["reason"] = event.reason;

    char body[256];
    serializeJson(doc, body, sizeof(body));

    HTTPClient http;
    if (!http.begin(url)) {
      allSent = false;
      break;
    }
    http.addHeader("Content-Type", "application/json");
    const int status = http.POST(reinterpret_cast<uint8_t *>(body), strlen(body));
    http.end();

    if (status != 201) {
      Serial.printf("[report] 보고 실패 (HTTP %d) — 다음 복귀에 재시도\n", status);
      allSent = false;
      break;
    }
    Serial.printf("[report] %s %s 보고 완료\n",
                  farmcontrol::relayName(event.relay),
                  farmcontrol::actionName(event.action));
  }

  if (allSent) {
    g_guard.clearPendingEvents();
  }
}

// --------------------------------------------------------------------------
// 연결
// --------------------------------------------------------------------------

void beginWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[wifi] %s 접속 시도\n", WIFI_SSID);
}

bool linkUp() { return WiFi.status() == WL_CONNECTED && g_mqtt.connected(); }

void serviceConnection(uint32_t now) {
  if (WiFi.status() != WL_CONNECTED) {
    if (now - g_lastReconnectMs < RECONNECT_INTERVAL_MS) {
      return;
    }
    g_lastReconnectMs = now;
    WiFi.reconnect();
    return;
  }
  if (!g_mqtt.connected()) {
    if (now - g_lastReconnectMs < RECONNECT_INTERVAL_MS) {
      return;
    }
    g_lastReconnectMs = now;
    connectMqtt();
  }
}

void updateStatusLed(uint32_t now, bool connected) {
  if (connected && !g_guard.offline()) {
    digitalWrite(PIN_STATUS_LED, HIGH);  // 상시 점등 = 서버 제어 중
  } else {
    digitalWrite(PIN_STATUS_LED, (now / 500) % 2 ? HIGH : LOW);  // 깜빡임 = 오프라인
  }
}

}  // namespace

// --------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.printf("\n[boot] %s — smartfarm_id=%d\n", DEVICE_NAME, SMARTFARM_ID);

  // 페일세이프: 릴레이는 무조건 OFF 에서 시작한다 (ARCHITECTURE 11.3-5).
  // 출력으로 바꾸기 **전에** 비활성 레벨을 써 둬야 부팅 순간의 글리치가 없다.
  for (uint8_t i = 0; i < farmcontrol::kRelayCount; ++i) {
#if RELAY_ACTIVE_LOW
    digitalWrite(kRelayPins[i], HIGH);
#else
    digitalWrite(kRelayPins[i], LOW);
#endif
    pinMode(kRelayPins[i], OUTPUT);
  }
  syncRelays();

  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, LOW);

  g_dht.begin();
  analogReadResolution(12);
#if USE_BH1750
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  g_lightMeterReady = g_lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
  if (!g_lightMeterReady) {
    Serial.println("[sensor] BH1750 초기화 실패 — 조도 없이는 측정값을 보내지 않는다");
  }
#endif

  loadThresholds();

  beginWifi();
  g_mqtt.setServer(MQTT_HOST, MQTT_PORT);
  g_mqtt.setCallback(onCommand);
  g_mqtt.setBufferSize(512);
  g_mqtt.setKeepAlive(30);

  // 워치독: 펌웨어가 멈춘 채 릴레이가 닫혀 있는 상태를 막는다.
  esp_task_wdt_init(WATCHDOG_TIMEOUT_S, /*panic=*/true);
  esp_task_wdt_add(nullptr);
}

void loop() {
  esp_task_wdt_reset();

  const uint32_t now = millis();
  serviceConnection(now);
  g_mqtt.loop();

  const bool connected = linkUp();

  if (now - g_lastSampleMs < SAMPLE_INTERVAL_MS) {
    updateStatusLed(now, connected);
    delay(10);
    return;
  }
  g_lastSampleMs = now;

  const Reading reading = readSensors();

  if (connected && reading.valid) {
    if (!publishReading(reading)) {
      Serial.println("[mqtt] sensor/data 발행 실패");
    }
  }

  // 오프라인이면 여기서 릴레이가 움직인다. 온라인이면 가드는 아무것도 하지
  // 않는다 — 판단 권한은 서버에 있다.
  const bool wasOffline = g_guard.offline();
  if (g_guard.update(now, connected, reading)) {
    syncRelays();
  }
  if (!wasOffline && g_guard.offline()) {
    Serial.println("[guard] 오프라인 안전 제어 시작");
  } else if (wasOffline && !g_guard.offline()) {
    Serial.println("[guard] 서버 복귀 — 판단 권한 반환");
  }

  // 복귀 처리가 남긴 기록까지 포함해, 온라인이면 밀린 보고를 흘려보낸다.
  if (connected) {
    reportOfflineActions();
  }

  updateStatusLed(now, connected);
}
