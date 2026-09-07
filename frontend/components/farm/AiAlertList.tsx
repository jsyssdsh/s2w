'use client';

import { AlertBanner, Skeleton } from '@/components/ui';
import type {
  AsyncState,
  ControlEvent,
  ShippingWindow,
  SmartfarmStatus,
  WholesalerRecommendation,
} from '@/lib/api';
import { formatMonthDay, formatTrend, formatWonPerKg } from '@/lib/format';
import { DEVICE_LABEL } from './SmartfarmPanel';
import { guidanceTone } from './PriceAnalysisPanel';

export interface AiAlert {
  id: string;
  tone: 'good' | 'warn' | 'bad' | 'info';
  title: string;
  body: string;
}

/**
 * SPEC 4.2 "AI 분석 알림" 을 만든다 (예: 시장 가격 상승 가능성 안내).
 *
 * 문구를 지어내지 않는다 — 시세 예측의 `guidance`, 추천 응답의 `notes`,
 * 스마트팜의 범위 이탈과 자동제어 기록을 그대로 읽어 옮긴다.
 */
export function buildAlerts({
  shippingWindow,
  recommendation,
  smartfarm,
  controls,
}: {
  shippingWindow: ShippingWindow | null;
  recommendation: WholesalerRecommendation | null;
  smartfarm: SmartfarmStatus | null;
  controls: ControlEvent[];
}): AiAlert[] {
  const alerts: AiAlert[] = [];

  if (shippingWindow) {
    const best = [...shippingWindow.rows]
      .filter((row) => !row.is_baseline)
      .sort((a, b) => b.expected_price_per_kg - a.expected_price_per_kg)[0];
    if (best) {
      alerts.push({
        id: `forecast-${best.date}`,
        tone: guidanceTone(best.guidance),
        title:
          best.change_pct_vs_baseline > 0
            ? '시장 가격 상승 가능성 안내'
            : '시장 가격 하락 가능성 안내',
        body:
          `${formatMonthDay(best.date)} 출하 시 예상 도매가격은 ` +
          `${formatWonPerKg(best.expected_price_per_kg)} 으로 기준일 대비 ` +
          `${formatTrend(best.change_pct_vs_baseline)}이 예상됩니다. ` +
          `${best.supply_outlook} · ${best.guidance}.`,
      });
    }
  }

  for (const note of recommendation?.notes ?? []) {
    alerts.push({ id: `note-${note}`, tone: 'warn', title: '출하 물량 안내', body: note });
  }

  for (const metric of smartfarm?.metrics ?? []) {
    if (metric.in_range) continue;
    alerts.push({
      id: `metric-${metric.metric}`,
      tone: 'bad',
      title: `${metric.label} 적정 범위 이탈`,
      body: `현재 ${metric.display} — 적정 기준 ${metric.target_display}. ${metric.control_display}.`,
    });
  }

  for (const event of controls.slice(0, 3)) {
    alerts.push({
      id: `control-${event.id}`,
      tone: 'info',
      title: `${DEVICE_LABEL[event.device]} 자동제어`,
      body: event.reason,
    });
  }

  return alerts;
}

export function AiAlertList({
  shippingWindow,
  recommendation,
  smartfarm,
  controls,
}: {
  shippingWindow: AsyncState<ShippingWindow>;
  recommendation: AsyncState<WholesalerRecommendation>;
  smartfarm: AsyncState<SmartfarmStatus>;
  controls: AsyncState<ControlEvent[]>;
}) {
  const loading =
    shippingWindow.status === 'loading' ||
    smartfarm.status === 'loading' ||
    controls.status === 'loading';

  const alerts = buildAlerts({
    shippingWindow: shippingWindow.data,
    recommendation: recommendation.data,
    smartfarm: smartfarm.data,
    controls: controls.data ?? [],
  });

  return (
    <section aria-labelledby="ai-alerts-heading" data-testid="ai-alerts">
      <h2 id="ai-alerts-heading" className="mb-3 text-base font-semibold tracking-tight">
        AI 분석 알림
      </h2>
      {loading && alerts.length === 0 ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : alerts.length === 0 ? (
        <AlertBanner tone="good" title="특이사항 없음">
          시세와 재배환경 모두 적정 범위입니다.
        </AlertBanner>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert) => (
            <AlertBanner key={alert.id} tone={alert.tone} title={alert.title}>
              {alert.body}
            </AlertBanner>
          ))}
        </div>
      )}
    </section>
  );
}
