import { expect, test } from '@playwright/test';

test('API 헬스체크가 ok 를 반환한다', async ({ request }) => {
  const response = await request.get('/api/health');
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toEqual({ status: 'ok' });
});

test('시드된 참조 데이터를 API 로 조회할 수 있다', async ({ request }) => {
  const regions = await (await request.get('/api/regions')).json();
  expect(regions.map((r: { name: string }) => r.name)).toContain('충남 논산시');

  const crops = await (await request.get('/api/crops')).json();
  expect(crops.map((c: { name: string }) => c.name)).toContain('토마토');
});

test('정적 내보내기된 프론트엔드가 컨테이너에서 서빙된다', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle('울퉁불퉁 농장 AI');
  await expect(page.getByTestId('app-shell')).toBeVisible();
});
