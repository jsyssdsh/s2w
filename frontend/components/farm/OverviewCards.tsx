'use client';

import { StatTile, StatTileGrid, Skeleton } from '@/components/ui';
import type { AsyncState, CropStatus, PriceForecast, WholesalerRecommendation } from '@/lib/api';
import { formatKg, formatRatio, formatWonPerKg } from '@/lib/format';

/**
 * SPEC 4.2 메인 현황 — 현재 작물 / 예상 수확량 / 현재 도매가 /
 * AI 추천 유통처 / 예상 수익률.
 *
 * 다섯 칸이 서로 다른 API 에서 오므로 칸마다 따로 로딩한다. 하나가 늦거나
 * 실패해도 나머지는 그대로 보인다.
 */

/** 아직 값이 없는 칸 — 자리를 유지해 레이아웃이 튀지 않게 한다. */
function PendingTile({ label, hint }: { label: string; hint: string }) {
  return (
    <StatTile label={label} value="—" hint={hint} />
  );
}

function tileFor<T>(
  state: AsyncState<T>,
  label: string,
  render: (data: T) => React.ReactNode,
): React.ReactNode {
  if (state.status === 'loading') {
    return (
      <div key={label} className="rounded-xl border border-line bg-surface p-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="mt-3 h-7 w-32" />
      </div>
    );
  }
  if (state.status === 'error') {
    return <PendingTile key={label} label={label} hint="불러오지 못했습니다" />;
  }
  return render(state.data);
}

export function OverviewCards({
  crop,
  forecast,
  recommendation,
  hasShipment,
}: {
  crop: CropStatus | null;
  forecast: AsyncState<PriceForecast>;
  recommendation: AsyncState<WholesalerRecommendation>;
  /** 추천의 기준이 될 출하가 있는가 — 없으면 추천 두 칸은 안내로 채운다 */
  hasShipment: boolean;
}) {
  const actuals = forecast.status === 'success' ? forecast.data.actuals : [];
  const latest = actuals.at(-1);
  const previous = actuals.at(-2);
  const deltaPct =
    latest && previous && previous.price_per_kg > 0
      ? ((latest.price_per_kg - previous.price_per_kg) / previous.price_per_kg) * 100
      : undefined;

  const best =
    recommendation.status === 'success' ? recommendation.data.candidates[0] : undefined;
  // 예상 수익률 = 예상 순수익 ÷ 판매금액 (SPEC 5.2 의 순수익 정의를 그대로 쓴다).
  const marginRatio = best && best.gross_krw > 0 ? best.net_profit_krw / best.gross_krw : undefined;

  return (
    <div data-testid="farm-overview">
    <StatTileGrid className="lg:grid-cols-5">
      <StatTile
        label="현재 작물"
        value={crop ? crop.crop_name : '—'}
        hint={crop ? `${crop.smartfarm_name} · ${crop.smartfarm_type}` : '재배 중인 작물이 없습니다'}
      />
      <StatTile
        label="예상 수확량"
        value={crop ? formatKg(crop.expected_yield_kg) : '—'}
        hint={crop ? `${crop.crop_name} 재배구역 기준` : '—'}
      />
      {tileFor(forecast, '현재 도매가', (data) => (
        <StatTile
          label="현재 도매가"
          value={latest ? formatWonPerKg(latest.price_per_kg) : '—'}
          deltaPct={deltaPct}
          hint={`${data.region_name} · ${data.as_of} 기준`}
        />
      ))}
      {!hasShipment ? (
        <PendingTile label="AI 추천 유통처" hint="출하를 등록하면 추천합니다" />
      ) : tileFor(recommendation, 'AI 추천 유통처', () =>
        best ? (
          <StatTile
            label="AI 추천 유통처"
            value={best.name}
            hint={`매입단가 ${formatWonPerKg(best.unit_price_krw)} · 거리 ${best.distance_km}km`}
          />
        ) : (
          <PendingTile label="AI 추천 유통처" hint="출하를 등록하면 추천합니다" />
        ),
      )}
      {!hasShipment ? (
        <PendingTile label="예상 수익률" hint="출하를 등록하면 계산합니다" />
      ) : tileFor(recommendation, '예상 수익률', () =>
        marginRatio !== undefined ? (
          <StatTile
            label="예상 수익률"
            value={formatRatio(marginRatio, { digits: 1 })}
            hint="판매금액 대비 예상 순수익"
          />
        ) : (
          <PendingTile label="예상 수익률" hint="출하를 등록하면 계산합니다" />
        ),
      )}
    </StatTileGrid>
    </div>
  );
}
