'use client';

import type { AsyncState } from '@/lib/api';
import { errorMessage } from '@/lib/api';
import { AlertBanner, EmptyState, SkeletonTable } from '@/components/ui';

/**
 * 패널 하나의 로딩 / 오류 / 비어 있음 세 상태를 한 곳에서 고른다.
 *
 * 유통업체 대시보드는 패널이 다섯이고 각각 다른 엔드포인트를 부른다. 한
 * 패널이 실패해도 나머지는 그대로 보여야 하므로, 분기를 화면마다 반복해서
 * 쓰지 않도록 여기로 모았다.
 */
export function PanelState<T>({
  state,
  rows = 4,
  cols = 4,
  emptyTitle = '표시할 데이터가 없습니다',
  emptyDescription,
  isEmpty,
  children,
}: {
  state: AsyncState<T>;
  rows?: number;
  cols?: number;
  emptyTitle?: string;
  emptyDescription?: React.ReactNode;
  /** 성공했지만 보여줄 것이 없는 경우 */
  isEmpty?: (data: T) => boolean;
  children: (data: T) => React.ReactNode;
}) {
  if (state.status === 'loading') return <SkeletonTable rows={rows} cols={cols} />;
  if (state.status === 'error') {
    return (
      <AlertBanner tone="bad" title="불러오지 못했습니다">
        {errorMessage(state.error)}
      </AlertBanner>
    );
  }
  if (isEmpty?.(state.data)) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }
  return <>{children(state.data)}</>;
}
