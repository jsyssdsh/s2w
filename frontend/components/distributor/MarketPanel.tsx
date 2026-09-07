'use client';

import { useCallback, useMemo } from 'react';
import { getMarketSnapshot, type MarketSnapshot } from '@/lib/api';
import { useApi } from '@/lib/useApi';
import {
  formatAxisDate,
  formatDate,
  formatKg,
  formatNumber,
  formatTrend,
  formatWonPerKg,
  trendOf,
} from '@/lib/format';
import { cn } from '@/lib/cn';
import { LineChart, type ChartDatum, type Series } from '@/components/charts';
import {
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui';
import { PanelState } from './PanelState';

/**
 * 실시간 시장 분석 (SPEC 4.3) — 품목별 가격/수요 등락률.
 *
 * 숫자는 `/api/distributor/market` 의 실측 도매 시세다. 기간 예측이 필요한
 * 화면(SPEC 4.2 시세 그래프)은 `/api/forecast/price` 를 직접 쓴다 — 예측
 * 모델은 캐시가 비어 있을 때 품목당 수십 초가 걸려서, 이 패널의 첫 그림을
 * 거기에 걸지 않는다.
 *
 * 차트는 품목마다 가격대가 크게 달라(딸기 9,800원 vs 배추 950원) 원 단위로는
 * 겹쳐 읽을 수 없다. 그래서 **구간 첫날을 100 으로 놓은 지수**로 그린다 —
 * 표가 절대값을, 차트가 상대 흐름을 맡는다.
 */

const BASELINE_INDEX = 100;

function toIndexSeries(snapshot: MarketSnapshot): {
  data: ChartDatum[];
  series: Series[];
} {
  const byDate = new Map<string, ChartDatum>();
  for (const row of snapshot.rows) {
    const baseline = row.series[0]?.price_per_kg;
    if (!baseline) continue;
    for (const point of row.series) {
      const datum = byDate.get(point.date) ?? { date: point.date };
      datum[row.crop_name] = Number(
        ((point.price_per_kg / baseline) * BASELINE_INDEX).toFixed(1),
      );
      byDate.set(point.date, datum);
    }
  }
  return {
    data: [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date))),
    series: snapshot.rows.map((row) => ({ dataKey: row.crop_name, label: row.crop_name })),
  };
}

function ChangeCell({ pct }: { pct: number }) {
  const trend = trendOf(pct);
  return (
    <span
      className={cn(
        'font-medium',
        trend === 'up' ? 'text-good' : trend === 'down' ? 'text-bad' : 'text-ink-muted',
      )}
    >
      <span aria-hidden>{trend === 'up' ? '▲ ' : trend === 'down' ? '▼ ' : ''}</span>
      {formatTrend(pct)}
    </span>
  );
}

export function MarketPanel({ regionId }: { regionId: number }) {
  const state = useApi<MarketSnapshot>(
    useCallback(
      (options) => getMarketSnapshot({ region_id: regionId }, options),
      [regionId],
    ),
  );

  const chart = useMemo(
    () => (state.data ? toIndexSeries(state.data) : null),
    [state.data],
  );

  return (
    <Card data-testid="market-panel">
      <CardHeader
        title="실시간 시장 분석"
        description="품목별 가격·수요 등락률입니다. 기준일 도매 시세를 같은 지역의 며칠 전 시세와 견줍니다."
      />
      <CardBody className="space-y-5 px-0 py-0">
        <PanelState
          state={state}
          rows={5}
          cols={4}
          emptyTitle="시세 이력이 없습니다"
          isEmpty={(data) => data.rows.length === 0}
        >
          {(data) => (
            <>
              <Table caption="품목별 가격·수요 등락률">
                <THead>
                  <TR>
                    <TH>품목</TH>
                    <TH align="right">현재 시세</TH>
                    <TH align="right">{data.lookback_days}일 전</TH>
                    <TH align="right">가격 등락률</TH>
                    <TH align="right">수요 등락률</TH>
                    <TH>시장 상황</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.rows.map((row) => (
                    <TR key={row.crop_id} data-testid="market-row">
                      <TD className="font-medium">{row.crop_name}</TD>
                      <TD align="right">{formatWonPerKg(row.price_per_kg)}</TD>
                      <TD align="right">{formatWonPerKg(row.previous_price_per_kg)}</TD>
                      <TD align="right">
                        <ChangeCell pct={row.price_change_pct} />
                      </TD>
                      <TD align="right">
                        <ChangeCell pct={row.demand_change_pct} />
                        <span className="block text-xs text-ink-muted">
                          거래량 {formatKg(row.volume_kg)}
                        </span>
                      </TD>
                      <TD className="text-ink-muted">{row.trend}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>

              {chart ? (
                <div className="px-5 pb-2">
                  <LineChart
                    data={chart.data}
                    xKey="date"
                    series={chart.series}
                    xLabel="날짜"
                    yLabel={`지수 (구간 첫날 = ${BASELINE_INDEX})`}
                    formatX={(value) => formatAxisDate(String(value))}
                    formatValue={(value) => formatNumber(value, 1)}
                    height={240}
                    ariaLabel="품목별 시세 지수 추이"
                  />
                </div>
              ) : null}
            </>
          )}
        </PanelState>
      </CardBody>
      {state.status === 'success' ? (
        <CardFooter>
          {state.data.region_name} · {formatDate(state.data.as_of)} 기준 ·
          최근 {state.data.lookback_days}일 등락 · 거래량을 수요의 대리 지표로 씁니다
        </CardFooter>
      ) : null}
    </Card>
  );
}
