import { expect, test, type Page } from '@playwright/test';

/**
 * 농가 대시보드 (SPEC 4.2) — 시드된 DB 를 상대로 한 화면 검증.
 *
 * 시드가 보장하는 값(docs/ARCHITECTURE.md 7절)만 단언한다:
 * 1동 토마토 재배구역 예상 수확량 1,000kg, 기준일(2026-08-08) 토마토 시세
 * 2,450원/kg, 도매처 순수익 순위 B > A > C, 센서 29.4℃ · 68% · 28%.
 *
 * 거래 기록은 DB 를 바꾸므로 파일 안에서 순서대로 돈다.
 */
test.describe.configure({ mode: 'serial' });

const TOMATO_YIELD = '1,000kg';
const ANCHOR_PRICE = '2,450원/kg';
const BEST_WHOLESALER = 'B 농산물유통';

async function gotoFarm(page: Page) {
  await page.goto('/farm/');
  await expect(page.getByRole('heading', { level: 1, name: '농가 대시보드' })).toBeVisible();
  await expect(page.getByTestId('farm-dashboard')).toBeVisible();
}

test('메인 현황 카드의 값이 모두 API 에서 온다', async ({ page }) => {
  await gotoFarm(page);

  const overview = page.getByTestId('farm-overview');
  await expect(overview).toContainText('현재 작물');
  await expect(overview).toContainText('토마토');
  await expect(overview).toContainText('예상 수확량');
  await expect(overview).toContainText(TOMATO_YIELD);
  // 현재 도매가 — 기준일 토마토 시세 (SPEC 5.1 워크드 예제)
  await expect(overview).toContainText(ANCHOR_PRICE);
  // AI 추천 유통처와 예상 수익률 — SPEC 5.2 순위 1위
  await expect(overview).toContainText('AI 추천 유통처');
  await expect(overview).toContainText(BEST_WHOLESALER);
  await expect(overview).toContainText('예상 수익률');
});

test('스마트팜 상태 패널이 적정 기준과 현재 값을 나란히 보여준다', async ({ page }) => {
  await gotoFarm(page);

  const panel = page.getByTestId('smartfarm-panel');
  for (const label of ['온도', '습도', '토양수분', '조도']) {
    await expect(panel).toContainText(label);
  }
  // SPEC 5.5 표: 22~27℃ 기준에 현재 29.4℃ — 범위 이탈
  await expect(panel).toContainText('22~27℃');
  await expect(panel).toContainText('29.4℃');
  await expect(panel).toContainText('범위 이탈');
  await expect(panel).toContainText('적정');
  // 워터펌프를 포함한 장치 상태
  await expect(page.getByTestId('smartfarm-devices')).toContainText('워터펌프');
});

test('AI 분석 알림이 예측·센서 결과에서 만들어진다', async ({ page }) => {
  await gotoFarm(page);

  const alerts = page.getByTestId('ai-alerts');
  await expect(alerts).toContainText('AI 분석 알림');
  await expect(alerts).toContainText(/시장 가격 (상승|하락) 가능성 안내/);
  // 센서가 범위를 벗어난 항목은 그대로 알림이 된다.
  await expect(alerts).toContainText('적정 범위 이탈');
});

test('가격 분석에 시세 변화 그래프와 출하일 비교표가 있다', async ({ page }) => {
  await gotoFarm(page);

  await page.getByRole('tab', { name: '가격 분석' }).click();
  const panel = page.getByTestId('price-analysis');
  await expect(panel).toContainText('시세 변화 그래프');
  await expect(panel.getByRole('img', { name: /도매 시세 실적과 예측 그래프/ })).toBeVisible();

  // SPEC 5.1 비교표의 다섯 행
  for (const row of [
    '예상 도매가격',
    '예상 판매금액',
    '현재 대비 가격 변동',
    '예상 시장 상황',
    '시스템 안내',
  ]) {
    await expect(panel).toContainText(row);
  }
  await expect(panel).toContainText(ANCHOR_PRICE);
  await expect(panel).toContainText(/즉시 출하 가능|출하 유지 권장|조기 출하 검토/);
});

test('작물 등록 → AI 유통 추천 → 도매처 선택이 거래 현황에 남는다', async ({ page }) => {
  await gotoFarm(page);

  // --- 작물 등록 (SPEC 4.2 빠른 기능) ---
  await page.getByRole('tab', { name: '작물 등록' }).click();
  const form = page.getByTestId('crop-register');
  await expect(form).toBeVisible();
  await form.getByLabel('품목').selectOption({ label: '토마토' });
  await form.getByLabel('출하량 (kg)').fill('1000');
  await form.getByLabel('출하 예정일').fill('2026-08-08');
  await form.getByLabel('등급').selectOption('special');
  await form.getByRole('button', { name: '작물 등록' }).click();

  // --- AI 유통 추천 (SPEC 5.2) ---
  const recommendation = page.getByTestId('wholesaler-recommendation');
  await expect(recommendation).toBeVisible();
  for (const column of ['도매처', '매입단가', '구매량', '운송비', '예상 순수익', '순위']) {
    await expect(recommendation).toContainText(column);
  }

  // 시드가 보장하는 순위: B > A > C
  const first = recommendation.getByTestId('candidate-1');
  await expect(first).toContainText(BEST_WHOLESALER);
  await expect(first).toContainText('2,580원/kg');
  await expect(first).toContainText('1,000kg');
  await expect(first).toContainText('1위');
  // 행마다 한국어 추천 근거가 붙는다.
  await expect(first).toContainText('예상 순수익');
  await expect(recommendation.getByTestId('candidate-2')).toContainText('A 청과도매');
  await expect(recommendation.getByTestId('candidate-3')).toContainText('C 도매시장');

  // --- 도매처 선택 → 거래 현황 (SPEC 7.1) ---
  await first.getByRole('button', { name: '이 도매처 선택' }).click();

  const history = page.getByTestId('deal-history');
  await expect(history).toBeVisible();
  await expect(history).toContainText(BEST_WHOLESALER);
  await expect(history).toContainText('거래 수락');
  await expect(history).toContainText('토마토 1,000kg');
});

test.describe('반응형', () => {
  for (const { name, width, height } of [
    { name: '375px 모바일', width: 375, height: 812 },
    { name: '1440px 데스크톱', width: 1440, height: 900 },
  ]) {
    test(`${name} 에서 가로 스크롤 없이 렌더된다`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await gotoFarm(page);
      await expect(page.getByTestId('farm-overview')).toBeVisible();
      await expect(page.getByTestId('smartfarm-panel')).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
