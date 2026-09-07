'use client';

import {
  Bar,
  CartesianGrid,
  Legend,
  BarChart as RechartsBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  AXIS_COLOR,
  AXIS_TICK,
  GRID_COLOR,
  TOOLTIP_STYLE,
  seriesColor,
  type ChartDatum,
  type Series,
  type TickFormatter,
  type ValueFormatter,
} from './theme';

/**
 * 막대 그래프 (SPEC 5.2 도매처별 예상 순수익 비교, 5.4 수급 집계).
 * `layout="vertical"` 이면 가로 막대 — 항목 이름이 긴 비교표에 쓴다.
 */
export function BarChart({
  data,
  xKey,
  series,
  xLabel,
  yLabel,
  formatX,
  formatValue,
  layout = 'horizontal',
  stacked = false,
  height = 260,
  ariaLabel,
}: {
  data: readonly ChartDatum[];
  xKey: string;
  series: readonly Series[];
  xLabel?: string;
  yLabel?: string;
  formatX?: TickFormatter;
  formatValue?: ValueFormatter;
  layout?: 'horizontal' | 'vertical';
  stacked?: boolean;
  height?: number;
  ariaLabel?: string;
}) {
  const vertical = layout === 'vertical';
  return (
    <figure
      className="w-full"
      role="img"
      aria-label={ariaLabel ?? `${series.map((s) => s.label).join(', ')} 비교 그래프`}
      style={{ height }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <RechartsBarChart
          data={data as ChartDatum[]}
          layout={layout}
          margin={{ top: 8, right: 12, bottom: xLabel ? 20 : 4, left: 4 }}
        >
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={vertical} horizontal={!vertical} />
          {vertical ? (
            <>
              <XAxis
                type="number"
                tick={AXIS_TICK}
                stroke={AXIS_COLOR}
                tickLine={false}
                label={
                  xLabel
                    ? { value: xLabel, position: 'insideBottom', offset: -12, fill: AXIS_COLOR, fontSize: 12 }
                    : undefined
                }
              />
              <YAxis
                type="category"
                dataKey={xKey}
                tick={AXIS_TICK}
                tickFormatter={formatX}
                stroke={AXIS_COLOR}
                tickLine={false}
                axisLine={false}
                width={88}
              />
            </>
          ) : (
            <>
              <XAxis
                dataKey={xKey}
                tick={AXIS_TICK}
                tickFormatter={formatX}
                stroke={AXIS_COLOR}
                tickLine={false}
                label={
                  xLabel
                    ? { value: xLabel, position: 'insideBottom', offset: -12, fill: AXIS_COLOR, fontSize: 12 }
                    : undefined
                }
              />
              <YAxis
                tick={AXIS_TICK}
                stroke={AXIS_COLOR}
                tickLine={false}
                axisLine={false}
                width={64}
                label={
                  yLabel
                    ? { value: yLabel, angle: -90, position: 'insideLeft', fill: AXIS_COLOR, fontSize: 12 }
                    : undefined
                }
              />
            </>
          )}
          <Tooltip
            {...TOOLTIP_STYLE}
            cursor={{ fill: 'var(--color-surface-muted)' }}
            formatter={(value) => (formatValue ? formatValue(Number(value)) : String(value))}
          />
          {series.length > 1 ? <Legend wrapperStyle={{ fontSize: '0.8125rem' }} /> : null}
          {series.map((item, index) => (
            <Bar
              key={item.dataKey}
              dataKey={item.dataKey}
              name={item.label}
              fill={item.color ?? seriesColor(index)}
              stackId={stacked ? 'stack' : undefined}
              radius={vertical ? [0, 4, 4, 0] : [4, 4, 0, 0]}
              isAnimationActive={false}
            />
          ))}
        </RechartsBarChart>
      </ResponsiveContainer>
    </figure>
  );
}
