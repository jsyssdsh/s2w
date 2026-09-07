'use client';

import { useCallback, useState } from 'react';
import {
  AlertBanner,
  Badge,
  Card,
  CardBody,
  CardHeader,
  Select,
  Skeleton,
} from '@/components/ui';
import { LineChart } from '@/components/charts';
import { cn } from '@/lib/cn';
import { formatClock, formatNumber } from '@/lib/format';
import { useApi } from '@/lib/useApi';
import {
  errorMessage,
  getSensorSeries,
  getSmartfarmStatus,
  type ControlDevice,
  type MetricStatus,
  type SensorMetric,
  type SmartfarmStatus,
} from '@/lib/api';

/**
 * 실시간 센서 · 센서 변화 그래프 · 이상 알림 (SPEC 4.5).
 *
 * 기준값과 자동제어 판단은 **전부 서버**에 있다 (docs/ARCHITECTURE.md §11).
 * 이 화면은 `GET /api/smartfarm/{id}/status` 가 준 표(측정 항목 / 적정 기준 /
 * 현재 상태 / 자동제어 결과)를 그대로 보여주고, 기준을 벗어난 항목에는
 * 자동제어 기록의 `reason` 문자열로 원인과 대응 방법을 붙인다.
 */

const DEVICE_LABELS: Record<ControlDevice, string> = {
  pump: '워터펌프',
  fan: '환기팬',
  light: '조명',
};

/** SPEC 4.5 가 나열한 순서 — 온도 / 습도 / 조도 / 워터펌프(토양수분) */
const CHART_METRICS: { value: SensorMetric; label: string; unit: string; digits: number }[] = [
  { value: 'temp_c', label: '온도', unit: '℃', digits: 1 },
  { value: 'humidity_pct', label: '습도', unit: '%', digits: 1 },
  { value: 'soil_moisture_pct', label: '토양수분', unit: '%', digits: 1 },
  { value: 'lux', label: '조도', unit: 'lx', digits: 0 },
];

const CHART_HOURS = 24;

function MetricCard({ metric }: { metric: MetricStatus }) {
  return (
    <div
      data-testid={`sensor-metric-${metric.metric}`}
      data-in-range={metric.in_range ? 'true' : 'false'}
      className={cn(
        'rounded-xl border px-4 py-3',
        metric.in_range ? 'border-line bg-surface' : 'border-bad/40 bg-bad-soft',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-ink-muted">{metric.label}</p>
        <Badge tone={metric.in_range ? 'good' : 'bad'} dot>
          {metric.in_range ? '적정' : '기준 이탈'}
        </Badge>
      </div>
      <p className="numeric mt-2 text-2xl font-semibold tracking-tight">{metric.display}</p>
      <p className="mt-1 text-xs text-ink-muted">적정 기준 {metric.target_display}</p>
      <p className="mt-1 text-xs">{metric.control_display}</p>
    </div>
  );
}

function Alerts({ status }: { status: SmartfarmStatus }) {
  const abnormal = status.metrics.filter((metric) => !metric.in_range);
  if (abnormal.length === 0) {
    return (
      <AlertBanner tone="good" title="모든 측정 항목이 적정 범위 안에 있습니다">
        자동제어가 개입할 이상 수치가 없습니다.
      </AlertBanner>
    );
  }

  return (
    <div className="space-y-3" data-testid="sensor-alerts">
      {abnormal.map((metric) => {
        const device = status.devices.find((item) => item.device === metric.device);
        return (
          <AlertBanner
            key={metric.metric}
            tone="bad"
            title={`${metric.label} 이상 — 현재 ${metric.display} (적정 ${metric.target_display})`}
          >
            <dl className="space-y-1">
              <div className="flex gap-2">
                <dt className="shrink-0 font-medium">원인</dt>
                <dd>
                  {device?.reason ??
                    `${metric.label} ${metric.display} 가 적정 기준 ${metric.target_display} 을(를) 벗어났습니다.`}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="shrink-0 font-medium">대응 방법</dt>
                <dd>
                  {metric.device
                    ? `${DEVICE_LABELS[metric.device]} ${
                        metric.device_action === 'on' ? '가동' : '정지'
                      } — ${metric.control_display}`
                    : metric.control_display}
                </dd>
              </div>
            </dl>
          </AlertBanner>
        );
      })}
    </div>
  );
}

export function SensorPanel({
  smartfarmId,
  smartfarmName,
  className,
}: {
  smartfarmId: number;
  smartfarmName: string;
  className?: string;
}) {
  const [metric, setMetric] = useState<SensorMetric>('temp_c');

  const status = useApi(
    useCallback((options) => getSmartfarmStatus(smartfarmId, options), [smartfarmId]),
  );
  const series = useApi(
    useCallback(
      (options) => getSensorSeries(smartfarmId, { metric, hours: CHART_HOURS }, options),
      [smartfarmId, metric],
    ),
  );

  const chartMetric = CHART_METRICS.find((item) => item.value === metric) ?? CHART_METRICS[0];
  const points = (series.data?.points ?? []).map((point) => ({
    ts: point.ts,
    value: point[metric] ?? null,
  }));

  return (
    <div className={cn('space-y-6', className)}>
      <Card>
        <CardHeader
          title="실시간 센서"
          description={`${smartfarmName} — 온도 · 습도 · 조도 · 워터펌프(토양수분)`}
          action={
            status.status === 'success' && status.data.ts ? (
              <Badge tone="neutral">측정 {formatClock(status.data.ts)}</Badge>
            ) : null
          }
        />
        <CardBody className="space-y-4">
          {status.status === 'error' ? (
            <AlertBanner tone="bad" title="센서 상태를 불러오지 못했습니다">
              {errorMessage(status.error)}
            </AlertBanner>
          ) : status.status === 'loading' ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3].map((index) => (
                <Skeleton key={index} className="h-32" />
              ))}
            </div>
          ) : (
            <>
              <div
                data-testid="sensor-metrics"
                className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
              >
                {status.data.metrics.map((item) => (
                  <MetricCard key={item.metric} metric={item} />
                ))}
              </div>

              <div className="flex flex-wrap gap-2" data-testid="device-states">
                {status.data.devices.map((device) => (
                  <Badge
                    key={device.device}
                    tone={device.action === 'on' ? 'info' : 'neutral'}
                    dot
                    className="max-w-full"
                  >
                    {DEVICE_LABELS[device.device]} {device.action === 'on' ? '가동 중' : '정지'}
                    {device.since ? ` · ${formatClock(device.since)}부터` : ''}
                  </Badge>
                ))}
              </div>

              <Alerts status={status.data} />
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="센서 변화 그래프"
          description={`최근 ${CHART_HOURS}시간`}
          action={
            <Select
              label="측정 항목"
              hideLabel
              aria-label="그래프 측정 항목"
              data-testid="sensor-metric-select"
              value={metric}
              onChange={(event) => setMetric(event.target.value as SensorMetric)}
              options={CHART_METRICS.map((item) => ({ value: item.value, label: item.label }))}
            />
          }
        />
        <CardBody>
          {series.status === 'error' ? (
            <AlertBanner tone="bad" title="센서 시계열을 불러오지 못했습니다">
              {errorMessage(series.error)}
            </AlertBanner>
          ) : series.status === 'loading' ? (
            <Skeleton className="h-[260px] w-full" />
          ) : (
            <div data-testid="sensor-chart">
              <LineChart
                data={points}
                xKey="ts"
                series={[{ dataKey: 'value', label: chartMetric.label }]}
                xLabel="측정 시각"
                yLabel={`${chartMetric.label} (${chartMetric.unit})`}
                formatX={(value) => formatClock(String(value))}
                formatValue={(value) =>
                  `${formatNumber(value, chartMetric.digits)}${chartMetric.unit}`
                }
                ariaLabel={`${smartfarmName} ${chartMetric.label} 변화 그래프`}
              />
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
