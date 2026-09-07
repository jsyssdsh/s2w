import { expect, test, type Page } from '@playwright/test';

/**
 * 화면을 가로지르는 규약 — 어느 한 화면의 기능이 아니라 **전부에 걸린 조건**.
 *
 *  1. 어떤 화면에서도 콘솔 오류·미처리 예외·네트워크 실패가 없다.
 *  2. 죽은 링크가 없다 — 모든 내부 링크가 실제 문서로 간다.
 *  3. API 오류 형태가 한 가지다 — 항상 `{"detail": ...}`.
 *  4. 숫자·한국어 표기가 화면을 가로질러 같다.
 */

const SCREENS = [
  { path: '/', name: '홈' },
  { path: '/farm/', name: '농가 대시보드' },
  { path: '/distributor/', name: '유통업체 대시보드' },
  { path: '/land/', name: '유휴토지 지도' },
  { path: '/land/detail/?id=1', name: '유휴토지 상세' },
] as const;

/**
 * 화면이 **일부러** 던져 보고 실패를 처리하는 요청. 이것만 4xx 를 허용한다.
 *
 * - `GET /api/forecast/price` — 유휴토지 상세의 AI 유통 추천은 필지가 속한
 *   지역부터 순서대로 시세 이력을 찾는다. 이력이 없는 지역은 404 가 정상이고
 *   화면은 다음 지역으로 넘어간다 (`components/land/DistributionAdvice.tsx`).
 */
const EXPECTED_4XX = [/\/api\/forecast\/price\?/];

/**
 * 브라우저가 응답 상태만 보고 스스로 찍는 줄. 아래 `response` 검사가 같은 사실을
 * URL 과 함께 더 정확히 잡으므로 여기서는 중복으로 세지 않는다.
 */
const BROWSER_RESOURCE_LINE = /^Failed to load resource:/;

/**
 * `net::ERR_ABORTED` 는 **브라우저가 스스로 취소한** 요청이다 — Next.js 가
 * 링크를 미리 당겨 오는 prefetch 는 응답을 받은 뒤 렌더러가 버리면서 항상 이
 * 상태가 된다. 서버가 실제로 잘못 답한 경우는 아래 `response` 검사가 상태
 * 코드로 잡으므로(HEAD 가 405 를 내던 시절도 그렇게 잡혔다), 여기서는 진짜
 * 네트워크 실패(연결 거부·DNS 실패 등)만 남긴다.
 */
const CANCELLED_BY_BROWSER = 'net::ERR_ABORTED';

interface Watcher {
  problems: string[];
}

function watch(page: Page): Watcher {
  const problems: string[] = [];

  page.on('pageerror', (error) => problems.push(`미처리 예외: ${error}`));
  page.on('console', (message) => {
    const text = message.text();
    if (message.type() === 'error' && !BROWSER_RESOURCE_LINE.test(text)) {
      problems.push(`콘솔 오류: ${text}`);
    }
  });
  page.on('requestfailed', (request) => {
    const reason = request.failure()?.errorText ?? '';
    if (reason === CANCELLED_BY_BROWSER) return;
    problems.push(`요청 실패: ${request.method()} ${request.url()} — ${reason}`);
  });
  page.on('response', (response) => {
    if (response.status() < 400) return;
    const url = response.url();
    if (EXPECTED_4XX.some((pattern) => pattern.test(url))) return;
    problems.push(`${response.status()} ${response.request().method()} ${url}`);
  });

  return { problems };
}

for (const screen of SCREENS) {
  test(`${screen.name} 화면에서 오류가 나지 않는다`, async ({ page }) => {
    const watcher = watch(page);

    await page.goto(screen.path);
    await expect(page.getByTestId('app-shell')).toBeVisible();
    // 클라이언트 페칭이 끝난 뒤에 봐야 의미가 있다 (정적 내보내기라 데이터는 전부 여기서 온다).
    await page.waitForLoadState('networkidle');

    expect(watcher.problems, `${screen.name}\n - ${watcher.problems.join('\n - ')}`).toEqual([]);
  });
}

test('내부 링크에 죽은 링크가 없다', async ({ page, request }) => {
  const seen = new Set<string>();

  for (const screen of SCREENS) {
    await page.goto(screen.path);
    await expect(page.getByTestId('app-shell')).toBeVisible();

    const hrefs = await page
      .locator('a[href]')
      .evaluateAll((anchors) =>
        anchors.map((anchor) => (anchor as HTMLAnchorElement).getAttribute('href') ?? ''),
      );
    for (const href of hrefs) {
      // 외부 링크와 페이지 내 앵커는 대상이 아니다.
      if (!href.startsWith('/') || href.startsWith('//')) continue;
      seen.add(href);
    }
  }

  expect(seen.size, '검사할 내부 링크가 하나는 있어야 한다').toBeGreaterThan(0);

  for (const href of seen) {
    const response = await request.get(href);
    expect(response.status(), `죽은 링크: ${href}`).toBeLessThan(400);
  }
});

test('API 오류가 어디서나 같은 모양이다', async ({ request }) => {
  const cases = [
    { name: '없는 농가', path: '/api/farms/9999', status: 404 },
    { name: '없는 필지', path: '/api/parcels/9999', status: 404 },
    { name: '없는 스마트팜', path: '/api/smartfarm/9999/status', status: 404 },
    { name: '없는 API 경로', path: '/api/nope', status: 404 },
    { name: '필수 파라미터 누락', path: '/api/alerts', status: 422 },
    { name: '잘못된 metric', path: '/api/smartfarm/1/readings?metric=nope', status: 422 },
  ] as const;

  for (const testCase of cases) {
    const response = await request.get(testCase.path);
    expect(response.status(), testCase.name).toBe(testCase.status);

    const body = await response.json();
    // FastAPI 기본 형식 하나만 쓴다 (docs/API.md "오류 응답").
    expect(Object.keys(body), testCase.name).toEqual(['detail']);
    expect(body.detail, testCase.name).toBeTruthy();
  }
});

test('숫자와 한국어 표기가 화면을 가로질러 같다', async ({ page }) => {
  // 금액은 천 단위 쉼표, 무게는 "1,000kg", 비율은 "12.3%" — lib/format.ts 한 곳에서 나온다.
  await page.goto('/farm/');
  const overview = page.getByTestId('farm-overview');
  await expect(overview).toContainText('1,000kg');
  await expect(overview).toContainText('2,450원/kg');

  await page.goto('/land/');
  await expect(page.getByTestId('parcel-summary')).toContainText(/토지 활용률 \d+(\.\d+)?%/);

  await page.goto('/distributor/');
  const market = page.getByTestId('market-panel');
  await expect(market.getByTestId('market-row').first()).toBeVisible({ timeout: 120_000 });
  await expect(market).toContainText('2,450원/kg');
});
