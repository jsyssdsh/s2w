'use client';

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart as RechartsLineChart,
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
 * 시계열 꺾은선 (SPEC 4.2 "작물 시세 변화 그래프", 4.5 "센서 변화 그래프").
 *
 * ```tsx
 * <LineChart
 *   data={prices}
 *   xKey="date"
 *   series={[{ dataKey: 'price', label: '도매가' }]}
 *   xLabel="출하일"
 *   yLabel="원/kg"
 *   formatX={formatAxisDate}
 *   formatValue={formatWonPerKg}
 * />
 * ```
 */
export function LineChart({
  data,
  xKey,
  series,
  xLabel,
  yLabel,
  formatX,
  formatValue,
  height = 260,
  ariaLabel,
}: {
  data: readonly ChartDatum[];
  xKey: string;
  series: readonly Series[];
  /** 축 라벨은 한국어로 (docs/ARCHITECTURE.md §8) */
  xLabel?: string;
  yLabel?: string;
  formatX?: TickFormatter;
  formatValue?: ValueFormatter;
  height?: number;
  ariaLabel?: string;
}) {
  return (
    <figure
      className="w-full"
      role="img"
      aria-label={ariaLabel ?? `${series.map((s) => s.label).join(', ')} 추이 그래프`}
      style={{ height }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <RechartsLineChart data={data as ChartDatum[]} margin={{ top: 8, right: 12, bottom: xLabel ? 20 : 4, left: 4 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
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
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(value) => (formatValue ? formatValue(Number(value)) : String(value))}
            labelFormatter={(label) => (formatX ? formatX(label as string | number) : String(label))}
          />
          {series.length > 1 ? <Legend wrapperStyle={{ fontSize: '0.8125rem' }} /> : null}
          {series.map((item, index) => (
            <Line
              key={item.dataKey}
              type="monotone"
              dataKey={item.dataKey}
              name={item.label}
              stroke={item.color ?? seriesColor(index)}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          ))}
        </RechartsLineChart>
      </ResponsiveContainer>
    </figure>
  );
}
