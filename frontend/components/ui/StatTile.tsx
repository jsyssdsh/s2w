import { cn } from '@/lib/cn';
import { formatTrend, trendOf, type Trend } from '@/lib/format';
import { Card } from './Card';

/**
 * 요약 지표 한 칸 (SPEC 4.3 "공급 가능 건수 / AI 추천 건수 / 예상 금액",
 * SPEC 4.4 "운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래").
 *
 * `value` 는 **이미 포맷된 문자열**을 받는다 — 포맷은 `lib/format.ts` 에서 한다.
 */
export function StatTile({
  label,
  value,
  unit,
  hint,
  /** 백분율 변동률(+5.3 / −5.3). 주면 상승·하락 표기를 붙인다. */
  deltaPct,
  /** 상승이 나쁜 지표(초과 공급량 등)는 색을 뒤집는다 */
  invertDelta = false,
  icon,
  className,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  deltaPct?: number;
  invertDelta?: boolean;
  icon?: React.ReactNode;
  className?: string;
}) {
  const trend: Trend | null = deltaPct === undefined ? null : trendOf(deltaPct);
  const deltaClass =
    trend === null || trend === 'flat'
      ? 'text-ink-muted'
      : (trend === 'up') !== invertDelta
        ? 'text-good'
        : 'text-bad';

  return (
    <Card className={cn('p-4', className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-ink-muted">{label}</p>
        {icon ? <span aria-hidden className="text-ink-muted">{icon}</span> : null}
      </div>
      <p className="mt-2 flex items-baseline gap-1">
        <span className="numeric text-2xl font-semibold tracking-tight">{value}</span>
        {unit ? <span className="text-sm text-ink-muted">{unit}</span> : null}
      </p>
      {deltaPct !== undefined ? (
        <p className={cn('mt-1 text-xs font-medium', deltaClass)}>
          <span aria-hidden>{trend === 'up' ? '▲' : trend === 'down' ? '▼' : '–'} </span>
          {formatTrend(deltaPct)}
        </p>
      ) : null}
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </Card>
  );
}

/** 지표 여러 개를 반응형으로 늘어놓는다 (375px 에서 1열, 넓으면 4열까지). */
export function StatTileGrid({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4',
        className,
      )}
    >
      {children}
    </div>
  );
}
