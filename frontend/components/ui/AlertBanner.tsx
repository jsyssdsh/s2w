import { cn } from '@/lib/cn';
import type { BadgeTone } from './Badge';

/**
 * 알림 띠 — SPEC 4.2 의 "AI 분석 알림", SPEC 5.4 의 수급 위험 경고,
 * 그리고 API 오류 표시에 함께 쓴다.
 */
const TONES: Record<Exclude<BadgeTone, 'neutral'>, string> = {
  good: 'border-good/30 bg-good-soft text-good',
  warn: 'border-warn/30 bg-warn-soft text-warn',
  bad: 'border-bad/30 bg-bad-soft text-bad',
  info: 'border-info/30 bg-info-soft text-info',
};

const ICONS: Record<Exclude<BadgeTone, 'neutral'>, string> = {
  good: '✓',
  warn: '!',
  bad: '!',
  info: 'i',
};

export function AlertBanner({
  tone = 'info',
  title,
  action,
  className,
  children,
}: {
  tone?: Exclude<BadgeTone, 'neutral'>;
  title?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      role={tone === 'bad' ? 'alert' : 'status'}
      className={cn('flex gap-3 rounded-xl border px-4 py-3 text-sm', TONES[tone], className)}
    >
      <span
        aria-hidden
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-current text-xs font-bold"
      >
        {ICONS[tone]}
      </span>
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={cn(title ? 'mt-1' : null, 'leading-relaxed')}>{children}</div> : null}
      </div>
      {action ? <div className="shrink-0 self-center">{action}</div> : null}
    </div>
  );
}
