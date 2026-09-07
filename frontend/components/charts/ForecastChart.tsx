'use client';

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
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
  type TickFormatter,
  type ValueFormatter,
} from './theme';

/**
 * 실적 + 예측을 한 축에 그리는 시계열 (SPEC 4.2 "작물 시세 변화 그래프",
 * SPEC 5.1 예측 구간).
 *
 * `LineChart` 와 다른 점은 **예측 신뢰구간을 띠로 깔아 준다**는 것뿐이다.
 * 띠는 recharts 의 범위 Area (`dataKey` 가 `[하한, 상한]` 배열) 로 그린다 —
 * 차트 의존성은 여전히 recharts 하나다.
 *
 * ```tsx
 * <ForecastChart
 *   data={points}          // { date, actual?, expected?, band?: [lower, upper] }
 *   xKey="date"
 *   actualKey="actual" expectedKey="expected" bandKey="band"
 *   formatX={formatAxisDate} formatValue={formatWonPerKg}
 * />
 * ```
 */
export function ForecastChart({
  data,
  xKey,
  actualKey,
  expectedKey,
  bandKey,
  actualLabel = '실적 시세',
  expectedLabel = '예측 시세',
  bandLabel = '예측 범위',
  boundaryX,
  boundaryLabel,
  yLabel,
  formatX,
  formatValue,
  height = 280,
  ariaLabel,
}: {
  data: readonly ChartDatum[];
  xKey: string;
  actualKey: string;
  expectedKey: string;
  /** `[하한, 상한]` 두 값을 담은 키. 없으면 띠를 그리지 않는다. */
  bandKey?: string;
  actualLabel?: string;
  expectedLabel?: string;
  bandLabel?: string;
  /** 실적과 예측이 갈리는 x 값 — 세로 기준선을 긋는다 */
  boundaryX?: string | number;
  boundaryLabel?: string;
  yLabel?: string;
  formatX?: TickFormatter;
  formatValue?: ValueFormatter;
  height?: number;
  ariaLabel?: string;
}) {
  const format = (value: unknown): string => {
    if (Array.isArray(value)) {
      const [low, high] = value as [number, number];
      return formatValue ? `${formatValue(low)} ~ ${formatValue(high)}` : `${low} ~ ${high}`;
    }
    return formatValue ? formatValue(Number(value)) : String(value);
  };

  return (
    <figure
      className="w-full"
      role="img"
      aria-label={ariaLabel ?? `${actualLabel}과 ${expectedLabel} 추이 그래프`}
      style={{ height }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data as ChartDatum[]} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey={xKey}
            tick={AXIS_TICK}
            tickFormatter={formatX}
            stroke={AXIS_COLOR}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            tick={AXIS_TICK}
            stroke={AXIS_COLOR}
            tickLine={false}
            axisLine={false}
            width={64}
            domain={['auto', 'auto']}
            label={
              yLabel
                ? { value: yLabel, angle: -90, position: 'insideLeft', fill: AXIS_COLOR, fontSize: 12 }
                : undefined
            }
          />
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(value, name) => [format(value), String(name)]}
            labelFormatter={(label) => (formatX ? formatX(label as string | number) : String(label))}
          />
          <Legend wrapperStyle={{ fontSize: '0.8125rem' }} />
          {boundaryX !== undefined ? (
            <ReferenceLine
              x={boundaryX}
              stroke={AXIS_COLOR}
              strokeDasharray="4 4"
              label={
                boundaryLabel
                  ? { value: boundaryLabel, position: 'insideTopLeft', fill: AXIS_COLOR, fontSize: 11 }
                  : undefined
              }
            />
          ) : null}
          {bandKey ? (
            <Area
              dataKey={bandKey}
              name={bandLabel}
              stroke="none"
              fill={seriesColor(1)}
              fillOpacity={0.18}
              isAnimationActive={false}
              connectNulls
            />
          ) : null}
          <Line
            dataKey={actualKey}
            name={actualLabel}
            type="monotone"
            stroke={seriesColor(0)}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
          <Line
            dataKey={expectedKey}
            name={expectedLabel}
            type="monotone"
            stroke={seriesColor(1)}
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  );
}
