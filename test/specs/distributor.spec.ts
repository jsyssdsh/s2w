import { expect, test, type Page } from '@playwright/test';

/**
 * 유통업체 대시보드 (SPEC 4.3) E2E.
 *
 * 시드(ANCHOR_DATE 2026-08-08)가 보장하는 값을 그대로 확인한다:
 *   - SPEC 5.4 양파 128톤 공급 vs 100톤 수요 → 위험 단계 "위험", 대응 28톤
 *   - SPEC 5.3 도매처 B 의 토마토 1,700kg 등급별 재고와 대응 판매처
 */

/**
 * 컨테이너를 막 띄운 직후의 첫 방문은 SPEC 5.1 시세 모델을 품목마다 학습한다
 * (`docs/api/price_forecast.md` — 학습 결과는 디스크에 캐시된다). 그래서 첫
 * 패널이 채워지기까지는 기본 5초보다 오래 걸릴 수 있다.
 */
const COLD_START_MS = 120_000;

// 기본 테스트 제한시간(30초)은 그 첫 학습을 기다리기에 모자라다.
test.describe.configure({ timeout: COLD_START_MS + 30_000 });

async function gotoDashboard(page: Page) {
  await page.goto('/distributor/');
  await expect(page.getByRole('heading', { level: 1, name: '유통업체 대시보드' })).toBeVisible();
  await expect(page.getByTestId('distributor-dashboard')).toBeVisible();
  // 자리(섹션)가 아니라 **내용**이 올 때까지 기다린다 — 이 뒤의 단언은 화면이
  // 이미 채워졌다고 가정한다.
  await expect(
    page.getByTestId('farm-recommendations').getByTestId('recommendation-row').first(),
  ).toBeVisible({ timeout: COLD_START_MS });
}

test('요약 타일이 공급 가능 건수 · AI 추천 건수 · 예상 금액을 보여준다', async ({ page }) => {
  await gotoDashboard(page);

  const panel = page.getByTestId('farm-recommendations');
  for (const label of ['공급 가능 건수', 'AI 추천 건수', '예상 금액']) {
    await expect(panel.getByText(label, { exact: true })).toBeVisible();
  }
  // 시드에는 토마토 1건 + 양파 4건이 창 안에 있다.
  await expect(panel.getByTestId('recommendation-row')).toHaveCount(5);
});

test('AI 추천 농가 리스트가 SPEC 4.3 의 열을 모두 갖추고 정렬된다', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await gotoDashboard(page);

  const panel = page.getByTestId('farm-recommendations');
  for (const header of ['농가', '출하일', '품질 등급', '공급량', '거리', '운송비', '권장 거래가', '예상 순수익', '추천 이유']) {
    await expect(panel.getByRole('columnheader', { name: new RegExp(header) })).toBeVisible();
  }

  // 기본 정렬은 예상 순수익 내림차순 — 첫 줄은 토마토 특상품 1,000kg.
  const first = panel.getByTestId('recommendation-row').first();
  await expect(first).toContainText('토마토');
  await expect(first).toContainText('특상품');

  // 공급량으로 다시 정렬하면 30,000kg 양파가 맨 위로 온다.
  await panel.getByTestId('sort-qty_kg').click();
  await expect(panel.getByTestId('recommendation-row').first()).toContainText('양파');
});

test('거래 요청 보내기가 요청을 남기고 버튼이 완료 상태로 바뀐다', async ({ page }) => {
  await gotoDashboard(page);

  const panel = page.getByTestId('farm-recommendations');
  // 요청을 보내면 목록이 다시 정렬될 수 있으므로, 줄을 출하 id 로 붙잡아 둔다.
  const openRow = panel
    .getByTestId('recommendation-row')
    .filter({ has: page.locator('[data-testid="deal-request-button"]:not([disabled])') })
    .first();
  const shipmentId = await openRow.getAttribute('data-shipment');
  const row = panel.locator(`[data-shipment="${shipmentId}"]`);
  const button = row.getByTestId('deal-request-button');

  await expect(button).toHaveText('거래 요청 보내기');
  await button.click();

  await expect(panel.getByTestId('deal-request-notice')).toContainText('거래 요청');
  await expect(button).toHaveText('요청 완료');
  await expect(button).toBeDisabled();
});

test('수급 위험 알림이 SPEC 5.4 양파 시나리오를 위험 단계로 보여준다', async ({ page }) => {
  await gotoDashboard(page);

  const panel = page.getByTestId('supply-risk-panel');
  const banner = panel.getByTestId('supply-risk-banner');
  // 기본 선택은 초과 비율이 가장 높은 품목이다. 양파를 골라 SPEC 5.4 예제를 본다.
  await expect(banner).toHaveAttribute('data-tier', '위험', { timeout: COLD_START_MS });
  await panel.getByTestId('supply-risk-crop').selectOption({ label: '양파 · 위험' });
  await expect(banner).toContainText('양파');
  await expect(banner).toHaveAttribute('data-tier', '위험');

  // SPEC 5.4 소급 분석 결과: 120톤 + 8톤 = 128톤, 수요 100톤, 초과 28톤.
  const volumes = panel.getByTestId('volume-row');
  await expect(volumes.filter({ hasText: '농가 출하 예정량' })).toContainText('120톤');
  await expect(volumes.filter({ hasText: '도매처 기존 재고량' })).toContainText('8톤');
  await expect(volumes.filter({ hasText: '전체 공급량' })).toContainText('128톤');
  await expect(volumes.filter({ hasText: '판매처 구매 수요량' })).toContainText('100톤');
  await expect(volumes.filter({ hasText: '예상 초과 공급량' })).toContainText('28톤');

  // 대응 방안 네 채널의 처리 물량 합계가 초과 28톤이다.
  await expect(panel.getByTestId('mitigation-row')).toHaveCount(4);
  await expect(panel.getByText('합계')).toBeVisible();
  await expect(panel.getByRole('row', { name: /합계/ })).toContainText('28톤');
});

test('판매처 연계 패널이 SPEC 5.3 토마토 1,700kg 재고를 등급별로 연결한다', async ({ page }) => {
  await gotoDashboard(page);

  const panel = page.getByTestId('buyer-link-panel');
  const rows = panel.getByTestId('buyer-link-row');
  await expect(rows).toHaveCount(4);

  // SPEC 5.3 표: 특상품 300 / 상품 700 / 규격 외 500 / 판매기한 임박 200.
  await expect(rows.filter({ hasText: '특상품' })).toContainText('300kg');
  await expect(rows.filter({ hasText: '규격 외' })).toContainText('500kg');
  const nearExpiry = rows.filter({ hasText: '판매기한 임박 200kg' });
  await expect(nearExpiry).toHaveCount(1);
  await expect(panel.getByText(/재고 1,700kg/)).toBeVisible();

  // 임박 로트는 색만이 아니라 글자로도 표시된다 (접근성).
  await expect(nearExpiry).toContainText(/임박 \d+일/);
});

test('실시간 시장 분석이 품목별 가격·수요 등락률을 보여준다', async ({ page }) => {
  await gotoDashboard(page);

  const panel = page.getByTestId('market-panel');
  await expect(panel.getByTestId('market-row')).toHaveCount(5, { timeout: COLD_START_MS });

  const tomato = panel.getByTestId('market-row').filter({ hasText: '토마토' });
  // SPEC 5.1 워크드 예제의 기준일 시세.
  await expect(tomato).toContainText('2,450원/kg');
  await expect(tomato).toContainText(/(상승|하락|변동 없음)/);
  await expect(panel.getByRole('img', { name: '품목별 시세 지수 추이' })).toBeVisible();
});

test.describe('반응형', () => {
  for (const { name, width, height } of [
    { name: '375px 모바일', width: 375, height: 812 },
    { name: '1440px 데스크톱', width: 1440, height: 900 },
  ]) {
    test(`${name} 에서 가로 스크롤 없이 렌더된다`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await gotoDashboard(page);

      await expect(page.getByTestId('farm-recommendations')).toBeVisible();
      await expect(page.getByTestId('supply-risk-panel')).toBeVisible();
      await expect(page.getByTestId('buyer-link-panel')).toBeVisible();
      await expect(page.getByTestId('market-panel')).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
