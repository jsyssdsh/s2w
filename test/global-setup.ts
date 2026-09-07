import { request } from '@playwright/test';

/**
 * 전역 준비 — SPEC 5.1 시세 예측 모델을 미리 학습시킨다.
 *
 * 예측은 `(품목, 지역)` 별로 모델을 처음 한 번 학습하고 디스크에 캐시한다
 * (docs/api/price_forecast.md). 컨테이너를 막 띄운 직후에는 그 학습이 화면의
 * 페치 제한시간보다 오래 걸려서, 어느 spec 이 맨 먼저 도느냐에 따라 결과가
 * 갈릴 수 있다. 여기서 한 번에 데워 두면 spec 실행 순서와 무관해진다.
 *
 * 학습이 실패해도 여기서 스위트를 죽이지는 않는다 — 그건 spec 이 판정할 일이다.
 */

const WARMUP_TIMEOUT_MS = 240_000;

export default async function globalSetup(): Promise<void> {
  const baseURL = process.env.BASE_URL ?? 'http://localhost:8000';
  const context = await request.newContext({ baseURL });

  try {
    const [crops, regions] = (await Promise.all([
      context.get('/api/crops').then((response) => response.json()),
      context.get('/api/regions').then((response) => response.json()),
    ])) as [{ id: number }[], { id: number }[]];

    // 시세 이력은 지역마다 있는 것이 아니다 — 404 면 다음 지역으로 넘어간다.
    // 화면(components/land/DistributionAdvice.tsx)이 하는 것과 같은 순회다.
    const ordered = [...regions].sort((a, b) => a.id - b.id);
    const started = Date.now();
    let warmed = 0;
    for (const crop of crops) {
      for (const region of ordered) {
        const response = await context.get(
          `/api/forecast/price?crop_id=${crop.id}&region_id=${region.id}`,
          { timeout: WARMUP_TIMEOUT_MS },
        );
        if (response.ok()) {
          warmed += 1;
          break;
        }
      }
    }
    console.log(
      `[setup] 시세 예측 모델 ${warmed}/${crops.length}건 준비 — ${Date.now() - started}ms`,
    );
  } catch (error) {
    console.warn(`[setup] 모델 예열 실패 (spec 이 판정한다): ${error}`);
  } finally {
    await context.dispose();
  }
}
