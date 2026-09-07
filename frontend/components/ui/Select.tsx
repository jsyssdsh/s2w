import { cn } from '@/lib/cn';

export interface SelectOption {
  value: string;
  label: string;
}

/**
 * 네이티브 `<select>` 를 감싼 것. 모바일에서 OS 기본 선택기가 뜨고
 * 키보드 접근성이 공짜로 따라온다 — 커스텀 드롭다운을 만들지 않는다.
 */
export function Select({
  label,
  options,
  className,
  id,
  /** 라벨을 시각적으로 숨긴다 (헤더처럼 자리가 없을 때) */
  hideLabel = false,
  ...rest
}: Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children'> & {
  label: string;
  options: readonly SelectOption[];
  hideLabel?: boolean;
}) {
  const selectId = id ?? `select-${label.replace(/\s+/g, '-')}`;
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <label
        htmlFor={selectId}
        className={cn('text-sm text-ink-muted whitespace-nowrap', hideLabel && 'sr-only')}
      >
        {label}
      </label>
      <select
        id={selectId}
        className={cn(
          'h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink',
          'transition-colors hover:bg-surface-muted',
        )}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
