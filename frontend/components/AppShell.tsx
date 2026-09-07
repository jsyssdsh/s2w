import { cn } from '@/lib/cn';

/**
 * 화면 한 개의 본문 틀. 모든 `page.tsx` 가 이걸로 감싼다 —
 * 제목·설명 위치와 좌우 여백이 화면마다 달라지지 않게 한다.
 *
 * 헤더/푸터는 `app/layout.tsx` 에 있다.
 */
export function AppShell({
  title,
  description,
  action,
  className,
  children,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** 제목 줄 오른쪽 영역 */
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      data-testid="app-shell"
      className={cn('mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10', className)}
    >
      {title ? (
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
            {description ? (
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-muted">
                {description}
              </p>
            ) : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}
