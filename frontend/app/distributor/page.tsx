import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { ButtonLink, EmptyState } from '@/components/ui';

export const metadata: Metadata = { title: '유통업체 대시보드' };

/**
 * 유통업체 대시보드 (SPEC 4.3) — 아직 화면이 없는 자리표시자.
 *
 * 홈의 링크가 죽지 않도록 라우트를 먼저 만들어 둔다. 이 화면을 채우는 bead 가
 * EmptyState 를 실제 내용으로 바꾼다.
 */
export default function Page() {
  return (
    <AppShell title="유통업체 대시보드" description="공급 가능 물량과 AI 추천 농가, 권장 거래가, 품목별 시장 등락률을 확인하고 거래를 요청합니다.">
      <EmptyState
        icon="📦"
        title="화면을 준비하고 있습니다"
        description="요약 지표·AI 추천 농가 리스트·실시간 시장 분석이 이 자리에 들어옵니다. (SPEC 4.3)"
        action={<ButtonLink href="/" variant="secondary">홈으로 돌아가기</ButtonLink>}
      />
    </AppShell>
  );
}
