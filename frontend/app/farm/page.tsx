import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { ButtonLink } from '@/components/ui';
import { FarmDashboard } from '@/components/farm/FarmDashboard';

export const metadata: Metadata = { title: '농가 대시보드' };

/**
 * 농가 대시보드 (SPEC 4.2).
 *
 * - 메인 현황: 현재 작물 · 예상 수확량 · 현재 도매가 · AI 추천 유통처 · 예상 수익률
 * - 빠른 기능: 작물 등록 / AI 유통 추천 / 가격 분석 / 거래 현황
 * - 스마트팜 상태: 온도 · 습도 · 조도 · 워터펌프
 * - AI 분석 알림
 *
 * 데이터는 전부 클라이언트에서 가져온다 (정적 내보내기 —
 * docs/ARCHITECTURE.md 8절). 화면 틀만 서버 컴포넌트로 둔다.
 */
export default function Page() {
  return (
    <AppShell
      title="농가 대시보드"
      description="현재 작물과 예상 수확량, 도매 시세, AI 추천 유통처와 예상 수익률, 스마트팜 센서 현황을 한 화면에서 봅니다."
      action={<ButtonLink href="/" variant="secondary">홈으로 돌아가기</ButtonLink>}
    >
      <FarmDashboard />
    </AppShell>
  );
}
