'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  errorMessage,
  getCrops,
  getDistributorWholesalers,
  getRegions,
  type Crop,
  type DistributorWholesaler,
  type Region,
} from '@/lib/api';
import { useApi } from '@/lib/useApi';
import {
  AlertBanner,
  Card,
  CardBody,
  Select,
  SkeletonTable,
  SkeletonText,
} from '@/components/ui';
import { BuyerLinkPanel } from './BuyerLinkPanel';
import { FarmRecommendationPanel } from './FarmRecommendationPanel';
import { MarketPanel } from './MarketPanel';
import { SupplyRiskPanel } from './SupplyRiskPanel';

/**
 * 유통업체 대시보드 본문 (SPEC 4.3).
 *
 * 정적 내보내기라 데이터는 전부 클라이언트에서 `lib/api.ts` 로 가져온다
 * (docs/ARCHITECTURE.md §8). 화면 위에는 선택기가 두 개뿐이다 —
 * **도매처**(추천 농가 · 판매처 연계)와 **지역**(시장 분석 · 수급 위험).
 * 로그인이 붙으면 도매처 선택기는 로그인한 사용자로 대체된다.
 */
export function DistributorDashboard() {
  const [wholesalerId, setWholesalerId] = useState<number | null>(null);
  const [regionId, setRegionId] = useState<number | null>(null);

  const wholesalers = useApi<DistributorWholesaler[]>(
    useCallback((options) => getDistributorWholesalers(options), []),
  );
  const regions = useApi<Region[]>(useCallback((options) => getRegions(options), []));
  const crops = useApi<Crop[]>(useCallback((options) => getCrops(options), []));

  /**
   * 기본 도매처는 **재고를 들고 있는 첫 도매처**다. 판매처 연계 패널이
   * 첫 화면부터 비어 있지 않도록 하는 것이 목적이고, 없으면 그냥 첫 도매처다.
   */
  const activeWholesalerId = useMemo(() => {
    if (wholesalerId !== null) return wholesalerId;
    const list = wholesalers.data ?? [];
    return (list.find((w) => w.inventory_lot_count > 0) ?? list[0])?.id ?? null;
  }, [wholesalerId, wholesalers.data]);

  /**
   * `/api/regions` 는 이름순으로 오지만, 지역을 생략했을 때 API 들이 고르는
   * 기본값은 **id 순 첫 지역**이다 (`app/services/distributor.default_region_id`).
   * 화면 기본값을 같은 규칙으로 맞춰 두지 않으면 선택기가 가리키는 지역과
   * 패널이 보여주는 지역이 어긋난다.
   */
  const defaultRegionId = useMemo(() => {
    const list = regions.data ?? [];
    if (list.length === 0) return null;
    return list.reduce((lowest, region) => (region.id < lowest.id ? region : lowest)).id;
  }, [regions.data]);

  const activeRegionId = regionId ?? defaultRegionId;

  if (wholesalers.status === 'error' || regions.status === 'error') {
    return (
      <AlertBanner tone="bad" title="대시보드를 불러오지 못했습니다">
        {errorMessage(wholesalers.error ?? regions.error)}
      </AlertBanner>
    );
  }

  return (
    <div className="space-y-6" data-testid="distributor-dashboard">
      <Card>
        <CardBody className="flex flex-wrap items-center gap-x-6 gap-y-3">
          {wholesalers.status === 'loading' || regions.status === 'loading' ? (
            <SkeletonText lines={1} className="w-full" />
          ) : (
            <>
              <Select
                label="도매처"
                data-testid="wholesaler-select"
                options={(wholesalers.data ?? []).map((w) => ({
                  value: String(w.id),
                  label: `${w.name} (${w.region_name})`,
                }))}
                value={activeWholesalerId === null ? '' : String(activeWholesalerId)}
                onChange={(event) => setWholesalerId(Number(event.target.value))}
              />
              <Select
                label="지역"
                data-testid="region-select"
                options={(regions.data ?? []).map((region) => ({
                  value: String(region.id),
                  label: region.name,
                }))}
                value={activeRegionId === null ? '' : String(activeRegionId)}
                onChange={(event) => setRegionId(Number(event.target.value))}
              />
            </>
          )}
        </CardBody>
      </Card>

      {wholesalers.status === 'loading' ? (
        <SkeletonTable rows={5} cols={6} />
      ) : activeWholesalerId === null ? (
        <AlertBanner tone="warn">등록된 도매처가 없습니다.</AlertBanner>
      ) : (
        <FarmRecommendationPanel
          wholesalerId={activeWholesalerId}
          crops={crops.data ?? []}
        />
      )}

      {/*
        지역이 정해지기 전에는 지역 패널을 띄우지 않는다. 띄우면 기본 지역으로
        한 번, 지역이 도착한 뒤 다시 한 번 — 같은 데이터를 두 번 부르게 된다.
        시세 예측은 첫 호출에서 모델을 학습하므로 그 한 번이 비싸다.
      */}
      {activeRegionId === null ? (
        <SkeletonTable rows={6} cols={2} />
      ) : (
        <SupplyRiskPanel regionId={activeRegionId} />
      )}

      {/* min-w-0: 칸 안의 표·차트가 좁은 화면에서 칸을 밀어내지 않게 한다 */}
      <div className="grid min-w-0 gap-6 xl:grid-cols-2">
        {activeWholesalerId === null ? null : (
          <div className="min-w-0">
            <BuyerLinkPanel wholesalerId={activeWholesalerId} />
          </div>
        )}
        {activeRegionId === null ? null : (
          <div className="min-w-0">
            <MarketPanel regionId={activeRegionId} />
          </div>
        )}
      </div>
    </div>
  );
}
