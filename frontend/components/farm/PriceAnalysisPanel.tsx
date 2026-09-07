'use client';

import { ForecastChart } from '@/components/charts';
import {
  AlertBanner,
  Badge,
  Card,
  CardBody,
  CardHeader,
  Skeleton,
  SkeletonTable,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui';
import {
  errorMessage,
  type AsyncState,
  type PriceForecast,
  type ShippingWindow,
  type ShippingWindowRow,
} from '@/lib/api';
import {
  formatAxisDate,
  formatKg,
  formatMonthDay,
  formatTrend,
  formatWonPerKg,
  formatMoney,
} from '@/lib/format';

/** SPEC 5.1 시스템 안내 세 가지의 색 구분. */
const GUIDANCE_TONE: Record<string, 'good' | 'warn' | 'info'> = {
  '즉시 출하 가능': 'info',
  '출하 유지 권장': 'good',
  '조기 출하 검토': 'warn',
};

export function guidanceTone(guidance: string): 'good' | 'warn' | 'info' {
  return GUIDANCE_TONE[guidance] ?? 'info';
}

/**
 * 빠른 기능 ③ 가격 분석 (SPEC 4.2 "향후 수정 계획" 의 시세 변화 그래프 +
 * SPEC 5.1 출하일 비교표).
 */
export function PriceAnalysisPanel({
  forecast,
  shippingWindow,
}: {
  forecast: AsyncState<PriceForecast>;
  shippingWindow: AsyncState<ShippingWindow>;
}) {
  return (
    <div className="space-y-6" data-testid="price-analysis">
      <Card>
        <CardHeader
          title="시세 변화 그래프"
          description={
            forecast.status === 'success'
              ? `${forecast.data.crop_name} · ${forecast.data.region_name} — 최근 실적과 향후 ${forecast.data.horizon_days}일 예측 (홀드아웃 MAPE ${forecast.data.model.mape_pct}%)`
              : '최근 도매 시세와 AI 예측 구간을 함께 봅니다.'
          }
        />
        <CardBody>
          {forecast.status === 'loading' ? (
            <Skeleton className="h-[280px] w-full" />
          ) : forecast.status === 'error' ? (
            <AlertBanner tone="bad">{errorMessage(forecast.error)}</AlertBanner>
          ) : (
            <PriceChart data={forecast.data} />
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="출하일 비교"
          description={
            shippingWindow.status === 'success'
              ? `${shippingWindow.data.crop_name} ${formatKg(shippingWindow.data.qty_kg)} 을 언제 출하할지 비교합니다.`
              : '후보 출하일별 예상 도매가격과 판매금액을 비교합니다.'
          }
        />
        <CardBody>
          {shippingWindow.status === 'loading' ? (
            <SkeletonTable rows={3} cols={5} />
          ) : shippingWindow.status === 'error' ? (
            <AlertBanner tone="bad">{errorMessage(shippingWindow.error)}</AlertBanner>
          ) : (
            <ShippingWindowTable rows={shippingWindow.data.rows} />
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function PriceChart({ data }: { data: PriceForecast }) {
  const points = [
    ...data.actuals.map((point) => ({
      date: point.date,
      actual: point.price_per_kg,
      expected: null,
      band: null,
    })),
    ...data.forecast.map((point) => ({
      date: point.date,
      actual: null,
      expected: point.expected_price_per_kg,
      band: [point.lower_price_per_kg, point.upper_price_per_kg],
    })),
  ];
  // 실적의 마지막 점을 예측 계열에도 넣어 선이 끊기지 않게 한다.
  const lastActual = data.actuals.at(-1);
  const seam = points.find((point) => point.date === lastActual?.date);
  if (seam && lastActual) {
    seam.expected = lastActual.price_per_kg;
    seam.band = [lastActual.price_per_kg, lastActual.price_per_kg];
  }

  return (
    <ForecastChart
      data={points}
      xKey="date"
      actualKey="actual"
      expectedKey="expected"
      bandKey="band"
      boundaryX={data.as_of}
      boundaryLabel="기준일"
      yLabel="원/kg"
      formatX={formatAxisDate}
      formatValue={formatWonPerKg}
      ariaLabel={`${data.crop_name} 도매 시세 실적과 예측 그래프`}
    />
  );
}

function ShippingWindowTable({ rows }: { rows: ShippingWindowRow[] }) {
  return (
    <Table caption="후보 출하일별 예상 도매가격·판매금액·시장 상황과 시스템 안내">
      <THead>
        <TR>
          <TH>비교항목</TH>
          {rows.map((row) => (
            <TH key={row.date} align="right">
              {`${formatMonthDay(row.date)} 출하`}
            </TH>
          ))}
        </TR>
      </THead>
      <TBody>
        <TR>
          <TH scope="row" className="text-left font-medium">예상 도매가격</TH>
          {rows.map((row) => (
            <TD key={row.date} align="right">
              {formatWonPerKg(row.expected_price_per_kg)}
            </TD>
          ))}
        </TR>
        <TR>
          <TH scope="row" className="text-left font-medium">예상 판매금액</TH>
          {rows.map((row) => (
            <TD key={row.date} align="right">
              {formatMoney(row.expected_revenue_krw)}
            </TD>
          ))}
        </TR>
        <TR>
          <TH scope="row" className="text-left font-medium">현재 대비 가격 변동</TH>
          {rows.map((row) => (
            <TD key={row.date} align="right">
              {row.is_baseline ? '기준' : formatTrend(row.change_pct_vs_baseline)}
            </TD>
          ))}
        </TR>
        <TR>
          <TH scope="row" className="text-left font-medium">예상 시장 상황</TH>
          {rows.map((row) => (
            <TD key={row.date} align="right">
              {row.supply_outlook}
            </TD>
          ))}
        </TR>
        <TR>
          <TH scope="row" className="text-left font-medium">시스템 안내</TH>
          {rows.map((row) => (
            <TD key={row.date} align="right">
              <Badge tone={guidanceTone(row.guidance)}>{row.guidance}</Badge>
            </TD>
          ))}
        </TR>
      </TBody>
    </Table>
  );
}
