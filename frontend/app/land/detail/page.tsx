import { Suspense } from 'react';
import type { Metadata } from 'next';
import { AppShell } from '@/components/AppShell';
import { Skeleton } from '@/components/ui';
import { ParcelDetailScreen } from '@/components/land/ParcelDetailScreen';

export const metadata: Metadata = { title: '유휴토지 상세' };

/**
 * 유휴토지 상세 (SPEC 4.5) — `/land/detail/?id=<필지 id>`.
 *
 * 정적 내보내기라 동적 세그먼트를 쓰려면 빌드 시점에 모든 id 를 알아야 한다.
 * 필지는 DB 에 있으므로 쿼리 파라미터로 받고, `useSearchParams` 를 쓰는 본체를
 * Suspense 로 감싼다 (정적 프리렌더 요구사항).
 */
export default function Page() {
  return (
    <Suspense
      fallback={
        <AppShell title="유휴토지 상세">
          <Skeleton className="h-64 w-full" />
        </AppShell>
      }
    >
      <ParcelDetailScreen />
    </Suspense>
  );
}
