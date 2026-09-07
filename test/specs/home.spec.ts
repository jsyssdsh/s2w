import { expect, test, type Page } from '@playwright/test';

/**
 * 홈 화면 (SPEC 4.1) 스모크 — 메뉴 선택, 연결 과정 시각화, 유형별 메뉴,
 * 그리고 세 라우트가 모두 살아 있는지.
 */

const ROUTES = [
  // `empty` 는 아직 화면이 없는 자리표시자 라우트다. 화면을 채우는 bead 가
  // 자기 라우트의 값을 false 로 바꾸고, 내용 검증은 그 화면의 spec 이 한다.
  { testId: 'entry-farm', path: '/farm/', heading: '농가 대시보드', empty: true },
  { testId: 'entry-distributor', path: '/distributor/', heading: '유통업체 대시보드', empty: true },
  { testId: 'entry-land', path: '/land/', heading: '유휴토지 지도', empty: false },
] as const;

async function gotoHome(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('app-shell')).toBeVisible();
}

test('홈 화면이 SPEC 4.1 의 세 메뉴를 보여준다', async ({ page }) => {
  await gotoHome(page);

  await expect(page.getByRole('heading', { level: 1, name: '울퉁불퉁 농장 AI' })).toBeVisible();

  const cards = page.getByTestId('entry-cards');
  for (const route of ROUTES) {
    await expect(cards.getByTestId(route.testId)).toBeVisible();
  }
});

test('농가 ↔ 유통업체 ↔ 유휴농지 연결 과정이 시각화된다', async ({ page }) => {
  await gotoHome(page);

  const flow = page.getByTestId('connection-flow');
  await expect(flow).toBeVisible();
  for (const node of ['유휴농지', '농가', '유통업체']) {
    await expect(flow.getByText(node, { exact: true })).toBeVisible();
  }
});

test('사용자 유형을 바꾸면 맞춤 메뉴가 따라 바뀐다', async ({ page }) => {
  await gotoHome(page);

  const menu = page.getByTestId('role-menu');
  await expect(menu).toContainText('농가 맞춤 메뉴');
  await expect(menu.getByRole('link', { name: /농가 대시보드/ })).toBeVisible();

  await page.getByTestId('role-switcher').selectOption('wholesaler');
  await expect(menu).toContainText('유통업체 맞춤 메뉴');
  await expect(menu.getByRole('link', { name: /유통업체 대시보드/ })).toBeVisible();
  await expect(menu.getByRole('link', { name: /농가 대시보드/ })).toHaveCount(0);
});

for (const route of ROUTES) {
  test(`홈에서 ${route.heading} 로 이동할 수 있다`, async ({ page }) => {
    await gotoHome(page);

    await page.getByTestId('entry-cards').getByTestId(route.testId).click();
    await expect(page).toHaveURL(new RegExp(`${route.path}$`));
    await expect(page.getByRole('heading', { level: 1, name: route.heading })).toBeVisible();
    // 아직 내용이 없는 화면이라도 빈 상태를 보여준다 — 죽은 링크가 없다.
    if (route.empty) {
      await expect(page.getByTestId('empty-state')).toBeVisible();
    }

    await page.getByRole('link', { name: '홈으로 돌아가기' }).first().click();
    await expect(page.getByTestId('entry-cards')).toBeVisible();
  });
}

test.describe('반응형', () => {
  for (const { name, width, height } of [
    { name: '375px 모바일', width: 375, height: 812 },
    { name: '1440px 데스크톱', width: 1440, height: 900 },
  ]) {
    test(`${name} 에서 가로 스크롤 없이 렌더된다`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await gotoHome(page);

      await expect(page.getByTestId('entry-cards')).toBeVisible();
      await expect(page.getByTestId('connection-flow')).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
