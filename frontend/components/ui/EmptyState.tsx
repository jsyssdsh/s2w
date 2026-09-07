import { cn } from '@/lib/cn';

/**
 * 보여줄 것이 없을 때. 아직 구현 전인 라우트도 이걸 쓴다 —
 * 링크가 죽은 페이지로 가는 일이 없어야 한다.
 */
export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      data-testid="empty-state"
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong',
        'bg-surface/60 px-6 py-14 text-center',
        className,
      )}
    >
      {icon ? (
        <span aria-hidden className="mb-3 text-3xl text-ink-muted">
          {icon}
        </span>
      ) : null}
      <p className="text-base font-semibold">{title}</p>
      {description ? (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-ink-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
