import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { DistributorDashboard } from '@/components/distributor/DistributorDashboard';

export const metadata: Metadata = { title: '유통업체 대시보드' };

/**
 * 유통업체 대시보드 (SPEC 4.3).
 *
 * 데이터는 전부 클라이언트에서 가져오므로 (정적 내보내기, ARCHITECTURE §8)
 * 이 파일은 틀만 잡고 본문은 `components/distributor` 로 넘긴다.
 */
export default function Page() {
  return (
    <AppShell
      title="유통업체 대시보드"
      description="공급 가능 물량과 AI 추천 농가, 권장 거래가, 품목별 시장 등락률을 확인하고 거래를 요청합니다."
    >
      <DistributorDashboard />
    </AppShell>
  );
}
