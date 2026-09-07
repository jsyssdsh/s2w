'use client';

import { useCallback, useState } from 'react';
import {
  AlertBanner,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Select,
  Skeleton,
  SkeletonTable,
} from '@/components/ui';
import {
  errorMessage,
  getCrops,
  getDeals,
  getFarms,
  getShipments,
  getWholesalers,
  type Farm,
} from '@/lib/api';
import { useApi } from '@/lib/useApi';
import { CropWorkspace } from './CropWorkspace';
import { DealHistoryPanel } from './DealHistoryPanel';

/**
 * 농가 대시보드 (SPEC 4.2) 의 데이터 진입점.
 *
 * 정적 내보내기라 서버에서 데이터를 못 가져오므로 (docs/ARCHITECTURE.md 8절)
 * 모든 호출은 클라이언트에서 `lib/api.ts` 를 거친다.
 */
export function FarmDashboard() {
  const farms = useApi(useCallback((options) => getFarms(options), []));
  const crops = useApi(useCallback((options) => getCrops(options), []));
  const [pickedFarmId, setPickedFarmId] = useState<number | null>(null);

  if (farms.status === 'loading') {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <SkeletonTable rows={4} cols={5} />
      </div>
    );
  }
  if (farms.status === 'error') {
    return <AlertBanner tone="bad">{errorMessage(farms.error)}</AlertBanner>;
  }
  if (farms.data.length === 0) {
    return (
      <EmptyState
        icon="🌾"
        title="등록된 농가가 없습니다"
        description="농가가 등록되면 재배 현황과 시세, AI 추천 유통처를 여기에서 봅니다."
      />
    );
  }

  const farm = farms.data.find((f) => f.farm_id === pickedFarmId) ?? farms.data[0];

  return (
    <div className="space-y-6" data-testid="farm-dashboard">
      {farms.data.length > 1 ? (
        <Select
          id="farm-picker"
          label="농가"
          value={String(farm.farm_id)}
          onChange={(event) => setPickedFarmId(Number(event.target.value))}
          options={farms.data.map((f) => ({
            value: String(f.farm_id),
            label: `${f.name} (${f.region_name})`,
          }))}
        />
      ) : null}
      <FarmView key={farm.farm_id} farm={farm} crops={crops.data ?? []} />
    </div>
  );
}

function FarmView({ farm, crops }: { farm: Farm; crops: { id: number; name: string; unit: string }[] }) {
  const [pickedCropId, setPickedCropId] = useState<number | null>(null);
  // 출하·거래를 새로 읽는 신호. `reload()` 대신 fetcher 를 바꿔 다시 읽으므로
  // 갱신하는 동안에도 직전 데이터가 그대로 보인다 (lib/useApi.ts 참고).
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  const shipments = useApi(
    useCallback(
      (options) => getShipments(farm.farm_id, options),
      // revision 은 fetcher 를 새 함수로 만들기 위한 것이다 — 이것이 곧 재조회 신호다.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [farm.farm_id, revision],
    ),
  );
  const deals = useApi(
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useCallback((options) => getDeals(options), [revision]),
  );
  const wholesalers = useApi(useCallback((options) => getWholesalers(options), []));

  const crop = farm.crops.find((c) => c.crop_id === pickedCropId) ?? farm.crops[0] ?? null;

  return (
    <div className="space-y-6">
      {farm.crops.length > 1 ? (
        <Select
          id="crop-picker"
          label="재배구역"
          value={String(crop?.crop_id ?? '')}
          onChange={(event) => setPickedCropId(Number(event.target.value))}
          options={farm.crops.map((c) => ({
            value: String(c.crop_id),
            label: `${c.smartfarm_name} · ${c.crop_name}`,
          }))}
        />
      ) : null}

      {crop ? (
        <CropWorkspace
          farm={farm}
          crop={crop}
          crops={crops}
          shipments={shipments}
          deals={deals}
          wholesalers={wholesalers}
          onDataChanged={refresh}
        />
      ) : (
        <>
          <Card>
            <CardHeader
              title="재배 중인 작물이 없습니다"
              description="스마트팜 재배구역을 등록하면 현황과 시세 예측이 여기에 나옵니다."
            />
            <CardBody>
              <EmptyState
                icon="🌱"
                title="재배구역 없음"
                description={`${farm.name} 에 연결된 스마트팜 재배구역이 없습니다. (SPEC 4.2)`}
              />
            </CardBody>
          </Card>
          <DealHistoryPanel deals={deals} shipments={shipments} wholesalers={wholesalers} />
        </>
      )}
    </div>
  );
}
