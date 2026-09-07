import { expect, test, type Page } from '@playwright/test';

/**
 * 유휴토지 지도 · 상세 (SPEC 4.4 / 4.5).
 *
 * 시드 데이터(SPEC 5.6)를 그대로 기대한다 — A 농지 900평 / B 농지 1,000평 /
 * C 농지 750평, 상태는 각각 상태 최상(녹) · 상태 양호(황) · 개선 필요(적).
 */

const PARCELS = [
  { id: 1, name: 'A 농지', color: 'green', rank: 1 },
  { id: 2, name: 'B 농지', color: 'amber', rank: 2 },
  { id: 3, name: 'C 농지', color: 'red', rank: 3 },
] as const;

async function gotoMap(page: Page) {
  await page.goto('/land/');
  await expect(page.getByRole('heading', { level: 1, name: '유휴토지 지도' })).toBeVisible();
  await expect(page.getByTestId('parcel-map')).toBeVisible();
}

/** 기본 조건(딸기 700~1,000평 · 예산 70만 원)으로 조건 비교를 실행한다. */
async function runCompare(page: Page) {
  await expect(page.getByTestId('filter-crop')).toHaveValue(/\d+/);
  await page.getByTestId('compare-submit').click();
  await expect(page.getByTestId('compare-table')).toBeVisible();
}

test('지도가 시드 농지를 상태 색으로 보여준다 (SPEC 4.4)', async ({ page }) => {
  await gotoMap(page);

  for (const parcel of PARCELS) {
    const marker = page.getByTestId(`parcel-marker-${parcel.id}`);
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute('data-color', parcel.color);
    await expect(marker).toContainText(parcel.name);
  }

  const legend = page.getByTestId('map-legend');
  await expect(legend).toContainText('상태 최상');
  await expect(legend).toContainText('상태 양호');
  await expect(legend).toContainText('개선 필요');

  // 요약 지표 (SPEC 4.4) — 신청으로 바뀌지 않는 전체 건수만 못박는다.
  const summary = page.getByTestId('parcel-summary');
  await expect(summary).toContainText('운영 중');
  await expect(summary).toContainText('전환 완료');
  await expect(summary).toContainText('오늘 신청량');
  await expect(summary).toContainText('AI 추천 거래');
  // 시나리오 spec(SPEC 7.3)이 농지를 새로 등록하므로 총 건수는 못박지 않는다.
  await expect(summary).toContainText(/전체 유휴농지 \d+곳/);
});

test('조건 비교가 SPEC 5.6 순위를 재현한다 (A 1위 / B 2위 / C 3위)', async ({ page }) => {
  await gotoMap(page);
  await runCompare(page);

  for (const parcel of PARCELS) {
    await expect(page.getByTestId(`compare-head-${parcel.id}`)).toHaveText(parcel.name);
    await expect(page.getByTestId(`compare-rank-${parcel.id}`)).toHaveText(`${parcel.rank}위`);
  }

  // 여섯 평가 축의 값이 표에 그대로 실린다 (SPEC 5.6 비교표).
  const table = page.getByTestId('compare-table');
  await expect(table).toContainText('농업용수');
  await expect(table).toContainText('도매처 거리');
  await expect(table).toContainText('900평');
  await expect(table).toContainText('미확보');
  // 농업용수가 없는 C 농지가 3위인 이유가 함께 보인다.
  await expect(page.getByTestId('compare-reasons')).toContainText('농업용수');
});

test('토양 상태 필터가 비교 대상을 좁힌다', async ({ page }) => {
  await gotoMap(page);
  await runCompare(page);

  await page.getByTestId('filter-soil').selectOption('1등급');
  await expect(page.getByTestId('compare-head-1')).toBeVisible();
  await expect(page.getByTestId('compare-head-2')).toHaveCount(0);
  await expect(page.getByTestId('compare-head-3')).toHaveCount(0);
});

test('지도에서 농지를 골라 상세 화면의 센서 그래프까지 간다 (SPEC 4.5)', async ({ page }) => {
  await gotoMap(page);

  await page.getByTestId('parcel-marker-1').click();
  const card = page.getByTestId('parcel-detail-card');
  await expect(card).toContainText('A 농지');
  await expect(card).toContainText('900평');

  await page.getByTestId('open-parcel-detail').click();
  await expect(page).toHaveURL(/\/land\/detail\/\?id=1$/);
  await expect(page.getByRole('heading', { level: 1, name: 'A 농지' })).toBeVisible();

  // 유휴토지 정보 — 재배 작물 / 영농 시작일 / 예상 수확량 / 스마트팜 유형
  const info = page.getByTestId('smartfarm-info');
  await expect(info).toContainText('토마토');
  await expect(info).toContainText('비닐하우스');
  await expect(info).toContainText('1,000kg');

  // 실시간 센서 — SPEC 5.5 시드값이 그대로 보인다
  const metrics = page.getByTestId('sensor-metrics');
  await expect(metrics.getByTestId('sensor-metric-temp_c')).toContainText('29.4℃');
  await expect(metrics.getByTestId('sensor-metric-temp_c')).toContainText('22~27℃');
  await expect(metrics.getByTestId('sensor-metric-temp_c')).toHaveAttribute(
    'data-in-range',
    'false',
  );
  await expect(metrics.getByTestId('sensor-metric-humidity_pct')).toHaveAttribute(
    'data-in-range',
    'true',
  );
  await expect(page.getByTestId('device-states')).toContainText('워터펌프');

  // 이상 수치 알림 — 원인과 대응 방법 (SPEC 4.5 향후 수정 계획)
  const alerts = page.getByTestId('sensor-alerts');
  await expect(alerts).toContainText('온도 이상');
  await expect(alerts).toContainText('원인');
  await expect(alerts).toContainText('대응 방법');

  // 센서 변화 그래프
  const chart = page.getByTestId('sensor-chart');
  await expect(chart).toBeVisible();
  await expect(chart.locator('svg .recharts-line path').first()).toBeVisible();

  await page.getByTestId('sensor-metric-select').selectOption('humidity_pct');
  await expect(chart.locator('svg .recharts-line path').first()).toBeVisible();

  // AI 유통 추천 결과 — 시세 예측 모델(SPEC 5.1)이 학습돼야 해서 넉넉히 기다린다.
  const advice = page.getByTestId('distribution-advice');
  await expect(advice.getByTestId('advice-recommendation')).toBeVisible({ timeout: 60_000 });
  await expect(advice).toContainText('예상 판매금액');
  await expect(advice).toContainText('B 농산물유통');
});

test('유휴 농지에 임대 신청을 넣으면 운영 중으로 바뀐다 (SPEC 7.3)', async ({ page, request }) => {
  // 재시도로 두 번째 신청이 409 가 되는 것을 피한다.
  const geojson = await (await request.get('/api/parcels/geojson')).json();
  const target = geojson.features.find(
    (feature: { properties: { id: number } }) => feature.properties.id === 3,
  );
  test.skip(target?.properties.status !== 'idle', 'C 농지가 이미 임대 신청된 상태');

  await gotoMap(page);
  await runCompare(page);

  await page.getByTestId('apply-3').click();
  const form = page.getByTestId('apply-form');
  await expect(form).toContainText('C 농지 임대 신청');
  await form.getByTestId('apply-name').fill('김청년');
  await form.getByTestId('apply-submit').click();

  const success = page.getByTestId('apply-success');
  await expect(success).toContainText('C 농지');
  await expect(success).toContainText('운영 중');

  // 지도와 요약 지표가 갱신된다 — 신청 후에는 임대 신청 버튼이 사라진다.
  await expect(page.getByTestId('apply-3')).toHaveCount(0);
});

test.describe('반응형', () => {
  for (const { name, width, height } of [
    { name: '375px 모바일', width: 375, height: 812 },
    { name: '1440px 데스크톱', width: 1440, height: 900 },
  ]) {
    test(`${name} 에서 가로 스크롤 없이 렌더된다`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await gotoMap(page);
      await runCompare(page);

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
