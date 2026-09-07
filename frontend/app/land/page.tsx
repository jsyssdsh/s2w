import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { ButtonLink, EmptyState } from '@/components/ui';

export const metadata: Metadata = { title: '유휴토지 지도' };

/**
 * 유휴토지 지도 (SPEC 4.4 / 4.5) — 아직 화면이 없는 자리표시자.
 *
 * 홈의 링크가 죽지 않도록 라우트를 먼저 만들어 둔다. 이 화면을 채우는 bead 가
 * EmptyState 를 실제 내용으로 바꾼다.
 */
export default function Page() {
  return (
    <AppShell title="유휴토지 지도" description="지도 위에서 휴경농지의 상태를 색으로 구분해 보고, 농지별 조건과 센서 현황을 상세히 비교합니다.">
      <EmptyState
        icon="🗺️"
        title="화면을 준비하고 있습니다"
        description="지도·상태 구분 범례·농지 상세 화면이 이 자리에 들어옵니다. (SPEC 4.4 / 4.5)"
        action={<ButtonLink href="/" variant="secondary">홈으로 돌아가기</ButtonLink>}
      />
    </AppShell>
  );
}
