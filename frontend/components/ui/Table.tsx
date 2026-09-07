import { cn } from '@/lib/cn';

/**
 * 표. SPEC 5장의 비교표(도매처 순위, 수급 집계, 농지 조건)가 모두 이 모양이다.
 *
 * 숫자 열은 `align="right"` 로 두면 자리수가 맞는 고정폭 숫자로 렌더된다.
 * 좁은 화면에서는 가로 스크롤한다 — 페이지 자체는 가로로 넘치지 않는다.
 */
export function Table({
  caption,
  className,
  children,
}: {
  /** 스크린리더용 표 설명. 시각적으로는 숨긴다. */
  caption?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full min-w-[32rem] border-collapse text-sm', className)}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return <thead className="border-b border-line text-xs text-ink-muted">{children}</thead>;
}

export function TBody({ children }: { children: React.ReactNode }) {
  return <tbody className="divide-y divide-line">{children}</tbody>;
}

export function TR({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr className={cn('transition-colors hover:bg-surface-muted/60', className)} {...rest}>
      {children}
    </tr>
  );
}

type Align = 'left' | 'right' | 'center';

const ALIGN: Record<Align, string> = {
  left: 'text-left',
  right: 'text-right numeric',
  center: 'text-center',
};

export function TH({
  align = 'left',
  className,
  children,
  ...rest
}: React.ThHTMLAttributes<HTMLTableCellElement> & { align?: Align }) {
  return (
    <th
      scope="col"
      className={cn('px-3 py-2.5 font-medium whitespace-nowrap', ALIGN[align], className)}
      {...rest}
    >
      {children}
    </th>
  );
}

export function TD({
  align = 'left',
  className,
  children,
  ...rest
}: React.TdHTMLAttributes<HTMLTableCellElement> & { align?: Align }) {
  return (
    <td className={cn('px-3 py-2.5', ALIGN[align], className)} {...rest}>
      {children}
    </td>
  );
}
