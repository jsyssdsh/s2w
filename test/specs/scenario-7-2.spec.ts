import { expect, test } from '@playwright/test';

/**
 * SPEC 7.2 운영 시나리오 — IoT 기반 스마트팜 자동제어, 한 줄로 이어서.
 *
 *   환경 센서 측정 → ESP32 제어기 → MQTT/Wi-Fi
 *     → 서버 판단 (재배환경 기준값과 비교)
 *     → 재배환경 변화 감지
 *     → 제어 명령 전송 (MQTT) → 릴레이 → 구동장치
 *     → 결과가 농가 대시보드와 유휴토지 상세에 보인다
 *
 * 앞의 절반은 Playwright 가 아니라 **스택이** 돌린다: docker-compose.test.yml 의
 * `sensor-sim` 서비스가 실물 ESP32 대신 `tools/sensor_sim.py` 를 Mosquitto 로
 * 발행하고, 서버가 그것을 판단해 `control_events` 를 남긴 뒤에야 이 spec 이
 * 시작한다 (compose 의 `depends_on: sensor-sim: service_healthy`).
 * 여기서 검증하는 것은 그 결과가 화면 두 곳에 도달하는가다.
 *
 * 대상은 **2동 딸기 재배구역(smartfarm 2)** 이다. 1동 토마토는 SPEC 5.5 표의
 * 값(29.4℃ · 68% · 28%)을 그대로 들고 있어야 다른 spec 이 성립하므로
 * 시뮬레이터가 건드리지 않는다.
 */

const SMARTFARM_ID = 2;
const SMARTFARM_NAME = '2동 딸기 재배구역';
const PARCEL_ID = 1; // 두 재배구역이 모두 올라앉은 A 농지
/** SPEC 5.5 자동제어 결과 열의 동사 — 환기팬 / 워터펌프 / 조명 */
const CONTROL_VERB = /(환기|급수|조명)/;

test.describe.configure({ mode: 'serial' });

test('서버가 기준값 이탈을 판단해 제어 명령을 남긴다', async ({ request }) => {
  const controls = await (await request.get(`/api/smartfarm/${SMARTFARM_ID}/controls`)).json();
  expect(controls.length, '시뮬레이터가 태운 자동제어 기록이 있어야 한다').toBeGreaterThan(0);

  // 시나리오 `all` 은 고온 → 환기, 토양건조 → 급수, 일몰 → 조명을 차례로 태운다.
  const devices = new Set(controls.map((event: { device: string }) => event.device));
  expect([...devices].sort()).toEqual(['fan', 'light', 'pump']);

  for (const event of controls) {
    // 명령마다 한국어 판단 근거가 붙는다 — "왜 켰는지" 가 화면에 그대로 쓰인다.
    expect(event.reason).toBeTruthy();
    expect(['on', 'off']).toContain(event.action);
    expect(event.smartfarm_id).toBe(SMARTFARM_ID);
  }

  // 켬 → 회복 → 정지까지 갔으므로 회복값이 기록된 명령이 있다 (SPEC 5.5 "환기 후 26.5℃").
  const recovered = controls.filter(
    (event: { value_after: number | null }) => event.value_after !== null,
  );
  expect(recovered.length).toBeGreaterThan(0);

  // 센서 측정값도 MQTT 로 들어와 시계열에 쌓였다.
  const series = await (
    await request.get(`/api/smartfarm/${SMARTFARM_ID}/readings?metric=temp_c`)
  ).json();
  expect(series.points.length).toBeGreaterThan(0);
});

test('제어 결과가 농가 대시보드의 스마트팜 상태에 보인다 (SPEC 4.2)', async ({ page }) => {
  await page.goto('/farm/');
  await expect(page.getByTestId('farm-dashboard')).toBeVisible();

  // 재배구역을 딸기로 바꾸면 그 재배구역의 센서·자동제어가 따라 온다.
  await page.getByLabel('재배구역').selectOption({ label: `${SMARTFARM_NAME} · 딸기` });

  const panel = page.getByTestId('smartfarm-panel');
  await expect(panel).toContainText(SMARTFARM_NAME);
  // SPEC 5.5 표 — 측정 항목 / 적정 기준 / 현재 상태 / 자동제어 결과
  for (const label of ['온도', '습도', '토양수분', '조도']) {
    await expect(panel).toContainText(label);
  }
  // 자동제어 결과 열에 시뮬레이터가 태운 개입이 남아 있다.
  await expect(panel).toContainText(CONTROL_VERB);

  // 릴레이가 붙은 구동장치 상태 (SPEC 4.2 "워터펌프 상태").
  await expect(page.getByTestId('smartfarm-devices')).toContainText('워터펌프');
});

test('같은 제어 결과가 유휴토지 상세에도 보인다 (SPEC 4.5)', async ({ page }) => {
  await page.goto(`/land/detail/?id=${PARCEL_ID}`);
  await expect(page.getByTestId('smartfarm-info')).toBeVisible();

  await page.getByTestId('smartfarm-select').selectOption({ label: SMARTFARM_NAME });
  await expect(page.getByTestId('smartfarm-info')).toContainText(SMARTFARM_NAME);

  const metrics = page.getByTestId('sensor-metrics');
  await expect(metrics.getByTestId('sensor-metric-temp_c')).toBeVisible();
  await expect(metrics).toContainText(CONTROL_VERB);

  // 센서 변화 그래프가 MQTT 로 들어온 측정값으로 그려진다 (SPEC 4.5).
  const chart = page.getByTestId('sensor-chart');
  await expect(chart.locator('svg .recharts-line path').first()).toBeVisible();

  await expect(page.getByTestId('device-states')).toContainText(/(워터펌프|환기팬|조명)/);
});
