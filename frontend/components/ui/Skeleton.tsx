import { cn } from '@/lib/cn';

/** 로딩 자리표시자. 실제 콘텐츠와 같은 높이를 차지해 레이아웃이 튀지 않게 한다. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('block animate-pulse rounded-md bg-surface-muted', className)}
    />
  );
}

/** 여러 줄짜리 문단 자리표시자 */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)} role="status" aria-label="불러오는 중">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={cn('h-4', index === lines - 1 && 'w-2/3')} />
      ))}
    </div>
  );
}

/** 표 자리표시자 */
export function SkeletonTable({ rows = 4, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="표를 불러오는 중">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex gap-3">
          {Array.from({ length: cols }, (_, col) => (
            <Skeleton key={col} className="h-8 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
