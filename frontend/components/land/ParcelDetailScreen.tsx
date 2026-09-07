'use client';

import { useCallback, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  AlertBanner,
  Badge,
  ButtonLink,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Select,
  Skeleton,
  StatTile,
  StatTileGrid,
  StatusBadge,
} from '@/components/ui';
import { AppShell } from '@/components/AppShell';
import { useApi } from '@/lib/useApi';
import { errorMessage, getParcelDetail, type ParcelSmartfarm } from '@/lib/api';
import { formatDate, formatKg, formatKm, formatMoney, formatPercent, formatPyeong } from '@/lib/format';
import { CONDITION_STATUS, STATUS_TONES } from '@/lib/land';
import { SensorPanel } from './SensorPanel';
import { DistributionAdvice } from './DistributionAdvice';

/**
 * 유휴토지 상세 (SPEC 4.5).
 *
 * 토지 활용률 · 유휴토지 정보(재배 작물, 영농 시작일, 예상 수확량, 스마트팜 유형)
 * · 실시간 센서와 변화 그래프 · AI 유통 추천 결과 · 이상 수치 알림.
 *
 * 정적 내보내기(`output: 'export'`)에서는 `/land/[id]` 동적 라우트를 빌드 시점에
 * 펼칠 수 없다 (필지가 DB 에 있다). 그래서 필지는 **쿼리 파라미터**로 받는다.
 */

function useParcelId(): number | null {
  const params = useSearchParams();
  const raw = params.get('id');
  const parsed = Number(raw);
  return raw !== null && Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function SmartfarmInfo({ smartfarm }: { smartfarm: ParcelSmartfarm }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-xs text-ink-muted">재배 작물</dt>
        <dd className="mt-0.5 font-medium">{smartfarm.crop_name}</dd>
      </div>
      <div>
        <dt className="text-xs text-ink-muted">영농 시작일</dt>
        <dd className="mt-0.5">{formatDate(smartfarm.started_on)}</dd>
      </div>
      <div>
        <dt className="text-xs text-ink-muted">예상 수확량</dt>
        <dd className="numeric mt-0.5">{formatKg(smartfarm.expected_yield_kg)}</dd>
      </div>
      <div>
        <dt className="text-xs text-ink-muted">스마트팜 유형</dt>
        <dd className="mt-0.5">{smartfarm.type}</dd>
      </div>
    </dl>
  );
}

export function ParcelDetailScreen() {
  const parcelId = useParcelId();
  const [smartfarmId, setSmartfarmId] = useState<number | null>(null);

  const parcel = useApi(
    useCallback(
      (options) =>
        parcelId === null
          ? Promise.resolve(null)
          : getParcelDetail(parcelId, options),
      [parcelId],
    ),
  );

  if (parcelId === null) {
    return (
      <AppShell title="유휴토지 상세">
        <EmptyState
          icon="🗺️"
          title="농지를 지정해 주세요"
          description="지도에서 농지를 고르면 이 화면으로 이어집니다."
          action={
            <ButtonLink href="/land/" variant="secondary">
              지도로 돌아가기
            </ButtonLink>
          }
        />
      </AppShell>
    );
  }

  if (parcel.status === 'error') {
    return (
      <AppShell title="유휴토지 상세">
        <AlertBanner tone="bad" title="농지 정보를 불러오지 못했습니다">
          {errorMessage(parcel.error)}
        </AlertBanner>
        <div className="mt-4">
          <ButtonLink href="/land/" variant="secondary">
            지도로 돌아가기
          </ButtonLink>
        </div>
      </AppShell>
    );
  }

  if (parcel.status === 'loading' || parcel.data === null) {
    return (
      <AppShell title="유휴토지 상세">
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </AppShell>
    );
  }

  const data = parcel.data;
  const smartfarms = data.smartfarms;
  const activeSmartfarm =
    smartfarms.find((farm) => farm.id === smartfarmId) ?? smartfarms[0] ?? null;

  return (
    <AppShell
      title={data.name}
      description={`${data.region_name} · ${formatPyeong(data.area_pyeong)} · 월 ${formatMoney(data.monthly_rent_krw)}`}
      action={
        <ButtonLink href="/land/" variant="secondary" size="sm">
          지도로 돌아가기
        </ButtonLink>
      }
    >
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={CONDITION_STATUS[data.condition]} />
          <Badge tone={STATUS_TONES[data.status]}>{data.status_label}</Badge>
          <Badge tone="neutral">토양 {data.soil_grade}</Badge>
          <Badge tone={data.water_access ? 'good' : 'bad'}>
            농업용수 {data.water_access ? '확보' : '미확보'}
          </Badge>
          <Badge tone="neutral">냉장창고 {data.cold_storage_label}</Badge>
          {data.owner ? (
            <span className="text-sm text-ink-muted">
              소유주 {data.owner.name}
              {data.owner.phone ? ` · ${data.owner.phone}` : ''}
            </span>
          ) : null}
        </div>

        <StatTileGrid>
          <StatTile
            label="토지 활용률"
            value={formatPercent(data.land_utilization_rate * 100, { digits: 1 })}
            icon="📐"
            hint="지역 전체 유휴농지 면적 대비 활용 중 면적"
          />
          <StatTile
            label="면적"
            value={formatPyeong(data.area_pyeong)}
            icon="🧭"
            hint={`토양 ${data.soil_grade}`}
          />
          <StatTile
            label="월 임대료"
            value={formatMoney(data.monthly_rent_krw)}
            icon="💰"
            hint={`냉장창고 ${data.cold_storage_label}`}
          />
          <StatTile
            label="임대 신청"
            value={String(data.application_count)}
            unit="건"
            icon="📝"
            hint={data.status_label}
          />
        </StatTileGrid>

        {/* --- 유휴토지 정보 (SPEC 4.5) --- */}
        <Card>
          <CardHeader
            title="유휴토지 정보"
            description="재배 작물 · 영농 시작일 · 예상 수확량 · 스마트팜 유형"
            action={
              smartfarms.length > 1 && activeSmartfarm ? (
                <Select
                  label="재배구역"
                  hideLabel
                  aria-label="재배구역 선택"
                  data-testid="smartfarm-select"
                  value={String(activeSmartfarm.id)}
                  onChange={(event) => setSmartfarmId(Number(event.target.value))}
                  options={smartfarms.map((farm) => ({
                    value: String(farm.id),
                    label: farm.name,
                  }))}
                />
              ) : null
            }
          />
          <CardBody>
            {activeSmartfarm ? (
              <div data-testid="smartfarm-info" className="space-y-3">
                <p className="text-sm font-medium">{activeSmartfarm.name}</p>
                <SmartfarmInfo smartfarm={activeSmartfarm} />
              </div>
            ) : (
              <EmptyState
                icon="🌱"
                title="아직 재배 중인 스마트팜이 없습니다"
                description="임대 신청이 접수되면 이 자리에 재배 작물과 예상 수확량이 표시됩니다."
              />
            )}
          </CardBody>
        </Card>

        {/* --- 실시간 센서 · 그래프 · 이상 알림 (SPEC 4.5) --- */}
        {activeSmartfarm ? (
          <SensorPanel smartfarmId={activeSmartfarm.id} smartfarmName={activeSmartfarm.name} />
        ) : null}

        {/* --- AI 유통 추천 결과 (SPEC 4.5) --- */}
        {activeSmartfarm ? (
          <DistributionAdvice
            cropId={activeSmartfarm.crop_id}
            cropName={activeSmartfarm.crop_name}
            qtyKg={activeSmartfarm.expected_yield_kg}
            parcel={{
              regionId: data.region_id,
              regionName: data.region_name,
              lat: data.lat,
              lon: data.lon,
            }}
            facilities={data.nearby_facilities}
          />
        ) : null}

        {/* --- 주변 시설 --- */}
        <Card>
          <CardHeader title="주변 시설" description="도매처 거리와 냉장창고 접근성" />
          <CardBody>
            <ul className="space-y-2 text-sm" data-testid="nearby-facilities">
              {data.nearby_facilities.map((facility) => (
                <li key={`${facility.kind}-${facility.name}`} className="flex flex-wrap items-center gap-x-2">
                  <Badge tone={facility.kind === 'wholesaler' ? 'info' : 'neutral'}>
                    {facility.kind === 'wholesaler' ? '도매처' : '냉장창고'}
                  </Badge>
                  <span className="font-medium">{facility.name}</span>
                  {facility.distance_km !== null ? (
                    <span className="numeric text-ink-muted">
                      {formatKm(facility.distance_km, 1)}
                    </span>
                  ) : null}
                  <span className="text-ink-muted">{facility.note}</span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}
