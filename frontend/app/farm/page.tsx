import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { ButtonLink, EmptyState } from '@/components/ui';

export const metadata: Metadata = { title: '농가 대시보드' };

/**
 * 농가 대시보드 (SPEC 4.2) — 아직 화면이 없는 자리표시자.
 *
 * 홈의 링크가 죽지 않도록 라우트를 먼저 만들어 둔다. 이 화면을 채우는 bead 가
 * EmptyState 를 실제 내용으로 바꾼다.
 */
export default function Page() {
  return (
    <AppShell title="농가 대시보드" description="현재 작물과 예상 수확량, 도매 시세, AI 추천 유통처와 예상 수익률, 스마트팜 센서 현황을 한 화면에서 봅니다.">
      <EmptyState
        icon="🌾"
        title="화면을 준비하고 있습니다"
        description="작물 현황·시세 그래프·AI 추천 도매처 목록이 이 자리에 들어옵니다. (SPEC 4.2)"
        action={<ButtonLink href="/" variant="secondary">홈으로 돌아가기</ButtonLink>}
      />
    </AppShell>
  );
}
