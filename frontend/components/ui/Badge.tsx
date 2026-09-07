import { cn } from '@/lib/cn';

/**
 * 상태 배지. SPEC 4.4 의 색 규약을 그대로 따른다 —
 * 상태 최상(녹) / 상태 양호(황) / 개선 필요(적).
 *
 * 색만으로 뜻을 전달하지 않도록 항상 글자를 함께 쓴다 (접근성).
 */
export type BadgeTone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

/** SPEC 4.4 의 농지·작물 상태 3단계 */
export type FarmStatus = 'best' | 'fair' | 'poor';

export const FARM_STATUS_LABELS: Record<FarmStatus, string> = {
  best: '상태 최상',
  fair: '상태 양호',
  poor: '개선 필요',
};

export const FARM_STATUS_TONES: Record<FarmStatus, BadgeTone> = {
  best: 'good',
  fair: 'warn',
  poor: 'bad',
};

const TONE_CLASSES: Record<BadgeTone, string> = {
  good: 'bg-good-soft text-good',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  info: 'bg-info-soft text-info',
  neutral: 'bg-surface-muted text-ink-muted',
};

const DOT_CLASSES: Record<BadgeTone, string> = {
  good: 'bg-good',
  warn: 'bg-warn',
  bad: 'bg-bad',
  info: 'bg-info',
  neutral: 'bg-ink-muted',
};

export function Badge({
  tone = 'neutral',
  dot = false,
  className,
  children,
}: {
  tone?: BadgeTone;
  /** 앞에 색 점을 찍는다 — 지도 범례처럼 색 구분이 핵심일 때 */
  dot?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap',
        TONE_CLASSES[tone],
        className,
      )}
    >
      {dot ? (
        <span aria-hidden className={cn('size-1.5 rounded-full', DOT_CLASSES[tone])} />
      ) : null}
      {children}
    </span>
  );
}

/** SPEC 4.4 의 상태 배지 — 색과 라벨이 항상 함께 간다. */
export function StatusBadge({
  status,
  className,
}: {
  status: FarmStatus;
  className?: string;
}) {
  return (
    <Badge tone={FARM_STATUS_TONES[status]} dot className={className}>
      {FARM_STATUS_LABELS[status]}
    </Badge>
  );
}
