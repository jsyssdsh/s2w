'use client';

import { useCallback } from 'react';
import {
  AlertBanner,
  Badge,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  EmptyState,
  SkeletonTable,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from '@/components/ui';
import { formatKg, formatKm, formatMoney, formatMonthDay, formatPercent, formatWonPerKg } from '@/lib/format';
import { haversineKm } from '@/lib/land';
import { useApi } from '@/lib/useApi';
import {
  ApiError,
  errorMessage,
  getPriceForecast,
  getRegions,
  getShippingWindow,
  type ParcelFacility,
  type RequestOptions,
  type ShippingWindow,
} from '@/lib/api';

/**
 * AI 유통 추천 결과 (SPEC 4.5).
 *
 * 필지에서 지금 재배 중인 작물과 예상 수확량을 그대로 들고
 * `POST /api/forecast/shipping-window` 에 물어, 언제 출하하면 얼마를 받는지
 * 비교표로 보여준다 (SPEC 5.1 의 활용 예시와 같은 표다).
 *
 * 시세 이력은 지역 단위라 필지가 있는 시군구에 이력이 없을 수 있다. 그때는
 * **가장 가까운 시군구**의 시세로 대체하고 어느 지역 기준인지 밝힌다 —
 * 조용히 빈 화면을 보여주는 것보다 낫다.
 */

/** 기준일 대비 며칠 뒤를 후보 출하일로 볼 것인가 (SPEC 5.1 비교표: 당일·1주·2주) */
const CANDIDATE_OFFSETS = [0, 3, 7, 14];
/** 시세 이력이 있는 지역을 찾을 때 최대 몇 곳까지 시도할 것인가 */
const MAX_REGION_TRIES = 4;

interface Advice {
  window: ShippingWindow;
  /** 필지의 지역이 아니라 인근 지역 시세를 쓴 경우 그 이름 */
  fallbackRegionName: string | null;
}

function addDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + days));
  return shifted.toISOString().slice(0, 10);
}

export function DistributionAdvice({
  cropId,
  cropName,
  qtyKg,
  parcel,
  facilities,
}: {
  cropId: number;
  cropName: string;
  qtyKg: number;
  parcel: { regionId: number; regionName: string; lat: number; lon: number };
  facilities: readonly ParcelFacility[];
}) {
  const { regionId, regionName, lat, lon } = parcel;

  const advice = useApi<Advice | null>(
    useCallback(
      async (options: RequestOptions) => {
        const regions = await getRegions(options);
        const ordered = [
          ...regions.filter((region) => region.id === regionId),
          ...regions
            .filter((region) => region.id !== regionId)
            .sort((a, b) => haversineKm({ lat, lon }, a) - haversineKm({ lat, lon }, b)),
        ].slice(0, MAX_REGION_TRIES);

        for (const region of ordered) {
          try {
            // 기준일(시세 이력의 마지막 날)을 먼저 확인해야 후보 출하일을 만들 수 있다.
            const forecast = await getPriceForecast(
              { crop_id: cropId, region_id: region.id, horizon: 1 },
              options,
            );
            const window = await getShippingWindow(
              {
                crop_id: cropId,
                region_id: region.id,
                qty_kg: qtyKg,
                candidate_dates: CANDIDATE_OFFSETS.map((offset) =>
                  addDays(forecast.as_of, offset),
                ),
              },
              options,
            );
            return {
              window,
              fallbackRegionName: region.id === regionId ? null : region.name,
            };
          } catch (error) {
            // 이 지역·품목의 시세 이력이 없을 뿐이다 — 다음 지역을 본다.
            if (error instanceof ApiError && error.status === 404) continue;
            throw error;
          }
        }
        return null;
      },
      [cropId, qtyKg, regionId, lat, lon],
    ),
  );

  const wholesalers = facilities.filter((facility) => facility.kind === 'wholesaler');
  const rows = advice.data?.window.rows ?? [];
  const best = rows.reduce<(typeof rows)[number] | null>(
    (found, row) => (found === null || row.expected_revenue_krw > found.expected_revenue_krw ? row : found),
    null,
  );

  return (
    <Card data-testid="distribution-advice">
      <CardHeader
        title="AI 유통 추천 결과"
        description={`${cropName} 예상 수확량 ${formatKg(qtyKg)} 기준 · 출하일별 예상 판매금액`}
      />
      <CardBody className="space-y-4">
        {advice.status === 'error' ? (
          <AlertBanner tone="bad" title="유통 추천을 계산하지 못했습니다">
            {errorMessage(advice.error)}
          </AlertBanner>
        ) : advice.status === 'loading' ? (
          <SkeletonTable rows={4} cols={5} />
        ) : advice.data === null ? (
          <EmptyState
            icon="📉"
            title="시세 이력이 없는 품목입니다"
            description={`${regionName} 인근에 ${cropName} 도매 시세 이력이 없어 추천을 만들 수 없습니다.`}
          />
        ) : (
          <>
            {advice.data.fallbackRegionName ? (
              <AlertBanner tone="info" title="인근 지역 시세 기준">
                {regionName}의 {cropName} 시세 이력이 없어{' '}
                <strong>{advice.data.fallbackRegionName}</strong> 도매 시세로 추천했습니다.
              </AlertBanner>
            ) : null}

            {best ? (
              <AlertBanner tone="good" title={`추천 출하일 — ${formatMonthDay(best.date)}`}>
                <span data-testid="advice-recommendation">
                  예상 도매가 {formatWonPerKg(best.expected_price_per_kg)} · 예상 판매금액{' '}
                  {formatMoney(best.expected_revenue_krw)} · {best.guidance}
                </span>
              </AlertBanner>
            ) : null}

            <Table caption={`${cropName} 출하일별 예상 판매금액 비교`}>
              <THead>
                <TR>
                  <TH>출하일</TH>
                  <TH align="right">예상 도매가격</TH>
                  <TH align="right">예상 판매금액</TH>
                  <TH align="right">기준 대비</TH>
                  <TH>예상 시장 상황</TH>
                  <TH>시스템 안내</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <TR key={row.date} className={row === best ? 'bg-good-soft/50' : undefined}>
                    <TD>
                      <span className="flex items-center gap-2">
                        {formatMonthDay(row.date)}
                        {row === best ? <Badge tone="good">AI 추천</Badge> : null}
                      </span>
                    </TD>
                    <TD align="right">{formatWonPerKg(row.expected_price_per_kg)}</TD>
                    <TD align="right">{formatMoney(row.expected_revenue_krw)}</TD>
                    <TD align="right">
                      {row.is_baseline ? '기준' : formatPercent(row.change_pct_vs_baseline, { signed: true, digits: 1 })}
                    </TD>
                    <TD>{row.supply_outlook}</TD>
                    <TD>{row.guidance}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </>
        )}

        {wholesalers.length > 0 ? (
          <div>
            <h3 className="text-sm font-semibold">주변 도매처</h3>
            <ul className="mt-2 space-y-1 text-sm">
              {wholesalers.map((facility) => (
                <li key={facility.name} className="flex flex-wrap items-center gap-x-2">
                  <span className="font-medium">{facility.name}</span>
                  {facility.distance_km !== null ? (
                    <span className="numeric text-ink-muted">{formatKm(facility.distance_km, 1)}</span>
                  ) : null}
                  <span className="text-ink-muted">{facility.note}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardBody>
      {advice.data ? (
        <CardFooter>
          예측 모델 홀드아웃 MAPE {formatPercent(advice.data.window.model.mape_pct, { digits: 2 })} ·
          기준일 {advice.data.window.as_of}
        </CardFooter>
      ) : null}
    </Card>
  );
}
