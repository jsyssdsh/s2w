import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { LandMapScreen } from '@/components/land/LandMapScreen';

export const metadata: Metadata = { title: '유휴토지 지도' };

/**
 * 유휴토지 관리 지도 (SPEC 4.4).
 *
 * 데이터는 전부 클라이언트에서 가져온다 (정적 내보내기라 서버 페칭이 없다) —
 * 화면 본체는 `components/land/LandMapScreen.tsx`.
 */
export default function Page() {
  return (
    <AppShell
      title="유휴토지 지도"
      description="지도 위에서 휴경농지의 상태를 색으로 구분해 보고, 농지별 조건과 센서 현황을 상세히 비교합니다."
    >
      <LandMapScreen />
    </AppShell>
  );
}
