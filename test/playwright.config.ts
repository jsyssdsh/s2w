import { defineConfig, devices } from '@playwright/test';

/**
 * E2E harness. BASE_URL points at a running FarmFlow container —
 * docker-compose.test.yml sets it to http://app:8000.
 *
 * **단일 워커**: 모든 spec 이 컨테이너 하나의 시드 DB 를 함께 쓴다. 격리가
 * 없으므로 출하 등록·거래 선택·임대 신청·농지 등록처럼 상태를 바꾸는 흐름이
 * 병렬로 돌면 서로의 집계(공급 가능 건수, 유휴농지 수, 순위)를 흔든다.
 * 워커를 하나로 두면 파일이 알파벳 순으로 차례차례 돌아 결과가 결정론적이 된다.
 * 전체 실행이 1분 남짓이라 이 대가가 싸다.
 */
export default defineConfig({
  testDir: './specs',
  // SPEC 5.1 예측 모델을 미리 학습시킨다 — 실행 순서에 결과가 흔들리지 않게.
  globalSetup: './global-setup.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:8000',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
