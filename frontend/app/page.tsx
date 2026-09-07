import { AppShell } from '@/components/AppShell';

/**
 * Placeholder landing page.
 *
 * The real 홈 화면 (SPEC 4.1 — 농가 대시보드 / 유통업체 대시보드 / 유휴토지
 * 지도 메뉴) is built by the frontend foundation bead. This page exists so the
 * static export, the container mount and the Playwright smoke test have
 * something stable to assert against.
 */
export default function HomePage() {
  return (
    <AppShell>
      <h1 className="text-3xl font-bold tracking-tight">울퉁불퉁 농장 AI</h1>
      <p className="mt-3 max-w-xl text-sm leading-relaxed">
        휴경농지·스마트팜·농산물 유통 데이터를 하나로 묶어, AI가 시세를 예측하고
        최적의 도매처·판매처·농지를 추천하는 생산-유통 통합 플랫폼입니다.
      </p>
    </AppShell>
  );
}
