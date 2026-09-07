import { expect, test, type Page } from '@playwright/test';

/**
 * SPEC 7.1 운영 시나리오 — AI 기반 유통 및 수익 추천, 한 줄로 이어서.
 *
 *   농가 출하 정보 등록
 *     → 시장 및 수요 데이터
 *     → AI 수익 분석 (거래처별 순수익)
 *     → 거래처 A / B / C 수익성 비교
 *     → 최적 거래처 추천
 *     → 농가 거래 선택
 *     → 실제 거래 결과가 다음 추천에 반영
 *
 * 화면별 검증은 farm.spec.ts / distributor.spec.ts 가 한다. 여기서 보는 것은
 * **연결**이다: 한 화면에서 고른 값이 DB 에 남고, 그 기록이 다음 추천의
 * 입력으로 되돌아오는가.
 */

const FARM_ID = 1;
const TOMATO = '토마토';
const SHIP_DATE = '2026-08-08'; // 시드 기준일 (ANCHOR_DATE)
const QTY_KG = 1000;

interface Candidate {
  rank: number;
  wholesaler_id: number;
  name: string;
  net_profit_krw: number;
  ranking_score_krw: number;
  reliability: { score: number; fulfilled: number; decided: number };
}

async function recommend(request: Page['request'], cropId: number): Promise<Candidate[]> {
  const response = await request.post('/api/recommendations/wholesalers', {
    data: { farm_id: FARM_ID, crop_id: cropId, qty_kg: QTY_KG, ship_date: SHIP_DATE },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).candidates as Candidate[];
}

function byName(candidates: Candidate[], name: string): Candidate {
  const found = candidates.find((candidate) => candidate.name.startsWith(name));
  expect(found, `${name} 후보가 추천 결과에 없다`).toBeTruthy();
  return found as Candidate;
}

test('SPEC 7.1 — 출하 등록에서 거래 선택까지, 그리고 그 선택이 다음 추천에 반영된다', async ({
  page,
  request,
}) => {
  const crops = await (await request.get('/api/crops')).json();
  const tomato = crops.find((crop: { name: string }) => crop.name === TOMATO);
  expect(tomato, '시드에 토마토가 있어야 한다').toBeTruthy();

  // --- 1) 시장 및 수요 데이터 -------------------------------------------
  // 추천이 딛고 서는 실측 시세다. SPEC 5.1 워크드 예제의 기준일 값.
  const market = await (await request.get('/api/distributor/market')).json();
  const tomatoRow = market.rows.find((row: { crop_name: string }) => row.crop_name === TOMATO);
  expect(tomatoRow.price_per_kg).toBe(2450);

  // 선택 전의 이행률을 찍어 둔다 — 이 값이 움직이는 것이 피드백 루프의 증거다.
  const before = await recommend(request, tomato.id);
  const runnerUpName = byName(before, 'A ').name;
  const bestBefore = byName(before, 'B ');
  const runnerUpBefore = byName(before, 'A ');

  // --- 2) 농가 출하 정보 등록 (화면) ------------------------------------
  await page.goto('/farm/');
  await expect(page.getByTestId('farm-dashboard')).toBeVisible();

  await page.getByRole('tab', { name: '작물 등록' }).click();
  const form = page.getByTestId('crop-register');
  await form.getByLabel('품목').selectOption({ label: TOMATO });
  await form.getByLabel('출하량 (kg)').fill(String(QTY_KG));
  await form.getByLabel('출하 예정일').fill(SHIP_DATE);
  await form.getByLabel('등급').selectOption('special');
  await form.getByRole('button', { name: '작물 등록' }).click();

  // --- 3) AI 수익 분석 · A/B/C 비교 · 최적 거래처 추천 (화면) -----------
  const recommendation = page.getByTestId('wholesaler-recommendation');
  await expect(recommendation).toBeVisible();
  const first = recommendation.getByTestId('candidate-1');
  // 순수익이 가장 높은 거래처가 1위로 제안된다 (SPEC 5.2 시드 기준 B).
  await expect(first).toContainText(bestBefore.name);
  await expect(first).toContainText('1위');
  await expect(recommendation.getByTestId('candidate-2')).toContainText(runnerUpName);
  await expect(recommendation.getByTestId('candidate-3')).toContainText('C 도매시장');
  // 근거가 함께 보인다 — 운송비·수수료를 뺀 예상 순수익.
  await expect(first).toContainText('예상 순수익');

  // --- 4) 농가 거래 선택 -------------------------------------------------
  await first.getByRole('button', { name: '이 도매처 선택' }).click();

  const history = page.getByTestId('deal-history');
  await expect(history).toContainText(bestBefore.name);
  await expect(history).toContainText('거래 수락');
  await expect(history).toContainText(`${TOMATO} ${QTY_KG.toLocaleString()}kg`);

  // --- 5) 선택이 DB 에 남는다 -------------------------------------------
  const shipments = await (await request.get(`/api/shipments?farm_id=${FARM_ID}`)).json();
  const mine = shipments.filter(
    (shipment: { crop_name: string; ship_date: string; deals: unknown[] }) =>
      shipment.crop_name === TOMATO && shipment.ship_date === SHIP_DATE,
  );
  const settled = mine.find((shipment: { deals: { status: string }[] }) =>
    shipment.deals.some((deal) => deal.status === 'accepted'),
  );
  expect(settled, '수락된 거래가 붙은 출하가 있어야 한다').toBeTruthy();

  const accepted = settled.deals.filter((deal: { status: string }) => deal.status === 'accepted');
  expect(accepted).toHaveLength(1);
  expect(accepted[0].wholesaler_id).toBe(bestBefore.wholesaler_id);
  expect(accepted[0].wholesaler_name).toBe(bestBefore.name);
  // 같은 출하의 나머지 제안은 자동으로 닫힌다 — 이것이 음의 신호다.
  const rejected = settled.deals.filter((deal: { status: string }) => deal.status === 'rejected');
  expect(rejected.length).toBeGreaterThan(0);

  // --- 6) 그 기록이 다음 추천에 반영된다 (SPEC 7.1 마지막 화살표) -------
  const after = await recommend(request, tomato.id);
  const bestAfter = byName(after, 'B ');
  const runnerUpAfter = byName(after, 'A ');

  // 고른 도매처는 이행 건수가 늘고, 거절된 도매처는 결론 건수가 늘어 이행률이 내려간다.
  expect(bestAfter.reliability.fulfilled).toBeGreaterThan(bestBefore.reliability.fulfilled);
  expect(runnerUpAfter.reliability.decided).toBeGreaterThan(runnerUpBefore.reliability.decided);
  expect(runnerUpAfter.reliability.score).toBeLessThan(runnerUpBefore.reliability.score);

  // 이행률은 정렬 기준값에만 붙는다 — 순수익 계산 자체는 건드리지 않는다.
  expect(runnerUpAfter.net_profit_krw).toBe(runnerUpBefore.net_profit_krw);
  expect(runnerUpAfter.ranking_score_krw).toBeLessThan(runnerUpAfter.net_profit_krw);

  // 감점 폭은 15% 로 묶여 있어 SPEC 5.2 의 결론(B 1위)은 흔들리지 않는다.
  expect(bestAfter.rank).toBe(1);
});
