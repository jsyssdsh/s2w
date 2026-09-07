'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  AlertBanner,
  Badge,
  ButtonLink,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Skeleton,
  SkeletonTable,
  StatTile,
  StatTileGrid,
  StatusBadge,
} from '@/components/ui';
import { useApi } from '@/lib/useApi';
import {
  errorMessage,
  getCrops,
  getParcelGeoJson,
  getParcelSummary,
  getRegions,
  matchParcels,
  type ParcelFeature,
  type ParcelMatch,
  type ParcelMatchRequest,
  type ParcelMatchResponse,
} from '@/lib/api';
import { formatMoney, formatNumber, formatPercent, formatPyeong } from '@/lib/format';
import { CONDITION_STATUS, parcelDetailHref, STATUS_TONES } from '@/lib/land';
import { ParcelMap, ParcelMapLegend, type ParcelMapPoint } from './ParcelMap';
import {
  DEFAULT_FILTERS,
  ParcelFilters,
  passesFilters,
  type ParcelFilterValues,
} from './ParcelFilters';
import { ParcelCompare } from './ParcelCompare';
import { ApplyForm, type ApplyTarget } from './ApplyForm';
import { ParcelRegisterForm } from './ParcelRegisterForm';

/**
 * 유휴토지 관리 지도 (SPEC 4.4).
 *
 * - 요약 지표: 운영 중 / 전환 완료 / 오늘 신청량 / AI 추천 거래
 * - 지도: 상태 최상(녹) / 상태 양호(황) / 개선 필요(적) + 범례
 * - 조건 비교와 임대 신청 (SPEC 4.4 향후 수정 계획 · SPEC 7.3)
 *
 * 정적 내보내기라 데이터는 전부 클라이언트에서 `lib/api.ts` 로 가져온다.
 */

const LEGEND = [
  { color: 'green' as const, label: '상태 최상' },
  { color: 'amber' as const, label: '상태 양호' },
  { color: 'red' as const, label: '개선 필요' },
];

/** SPEC 5.6 활용 예시가 딸기라서, 작물 목록에 있으면 이걸 기본값으로 둔다. */
const DEFAULT_CROP_NAME = '딸기';

export function LandMapScreen() {
  const [rawValues, setValues] = useState<ParcelFilterValues>({ cropId: 0, ...DEFAULT_FILTERS });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [query, setQuery] = useState<ParcelMatchRequest | null>(null);
  const [applyTarget, setApplyTarget] = useState<ApplyTarget | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const [registered, setRegistered] = useState<string | null>(null);

  const crops = useApi(useCallback((options) => getCrops(options), []));
  const regions = useApi(useCallback((options) => getRegions(options), []));

  // 작물 목록이 도착하기 전에는 고를 작물이 없다. 기본값을 state 에 밀어 넣는
  // 대신 렌더할 때 채운다 — 효과 안에서 setState 하면 렌더가 한 번 더 돈다.
  const defaultCropId =
    crops.data?.find((crop) => crop.name === DEFAULT_CROP_NAME)?.id ?? crops.data?.[0]?.id ?? 0;
  const values: ParcelFilterValues = useMemo(
    () => ({ ...rawValues, cropId: rawValues.cropId || defaultCropId }),
    [rawValues, defaultCropId],
  );

  const regionId = values.regionId;
  const geo = useApi(useCallback((options) => getParcelGeoJson(regionId, options), [regionId]));
  const summary = useApi(useCallback((options) => getParcelSummary(regionId, options), [regionId]));
  const match = useApi<ParcelMatchResponse | null>(
    useCallback(
      (options) => (query ? matchParcels(query, options) : Promise.resolve(null)),
      [query],
    ),
  );

  const features: ParcelFeature[] = useMemo(() => geo.data?.features ?? [], [geo.data]);
  const soilGrades = useMemo(
    () => [...new Set(features.map((feature) => feature.properties.soil_grade))].sort(),
    [features],
  );

  const filteredResults = useMemo(
    () => (match.data?.results ?? []).filter((result) => passesFilters(result, values)),
    [match.data, values],
  );
  const rankById = useMemo(
    () => new Map(filteredResults.map((result) => [result.parcel_id, result.rank])),
    [filteredResults],
  );

  const points: ParcelMapPoint[] = features.map((feature) => {
    const props = feature.properties;
    return {
      id: props.id,
      name: props.name,
      lat: feature.geometry.coordinates[1],
      lon: feature.geometry.coordinates[0],
      color: props.color,
      statusLabel: props.status_label,
      conditionLabel: props.condition_label,
      rank: rankById.get(props.id),
      muted: !passesFilters(props, values) || (match.data !== null && !rankById.has(props.id)),
    };
  });

  const legendItems = LEGEND.map((item) => ({
    ...item,
    count: features.filter((feature) => feature.properties.color === item.color).length,
  }));

  const contextPoints = (regions.data ?? []).map((region) => ({
    id: region.id,
    name: region.name,
    lat: region.lat,
    lon: region.lon,
  }));

  const selected = features.find((feature) => feature.properties.id === selectedId) ?? null;
  const cropName =
    crops.data?.find((crop) => crop.id === values.cropId)?.name ?? match.data?.crop_name ?? '';

  function runCompare() {
    setApplyTarget(null);
    setApplied(null);
    setRegistered(null);
    setQuery({
      crop_id: values.cropId,
      area_min_pyeong: values.areaMinPyeong,
      area_max_pyeong: values.areaMaxPyeong,
      budget_krw_per_month: values.budgetManWon * 10_000,
      region_id: values.regionId,
    });
  }

  function startApply(parcel: ParcelMatch | ParcelFeature['properties'], score?: number | null) {
    setApplied(null);
    setApplyTarget({
      parcelId: 'parcel_id' in parcel ? parcel.parcel_id : parcel.id,
      name: parcel.name,
      areaPyeong: parcel.area_pyeong,
      monthlyRentKrw: parcel.monthly_rent_krw,
      matchScore: score ?? null,
    });
  }

  return (
    <div className="space-y-6">
      {/* --- 요약 지표 (SPEC 4.4) --- */}
      {summary.status === 'error' ? (
        <AlertBanner tone="bad" title="요약 지표를 불러오지 못했습니다">
          {errorMessage(summary.error)}
        </AlertBanner>
      ) : (
        <div data-testid="parcel-summary">
        <StatTileGrid>
          {summary.status === 'loading' ? (
            <>
              <Skeleton className="h-[104px]" />
              <Skeleton className="h-[104px]" />
              <Skeleton className="h-[104px]" />
              <Skeleton className="h-[104px]" />
            </>
          ) : (
            <>
              <StatTile
                label="운영 중"
                value={formatNumber(summary.data.operating_count)}
                unit="곳"
                icon="🌱"
                hint={`전체 유휴농지 ${formatNumber(summary.data.total_count)}곳`}
              />
              <StatTile
                label="전환 완료"
                value={formatNumber(summary.data.converted_count)}
                unit="곳"
                icon="✅"
                hint={`토지 활용률 ${formatPercent(summary.data.land_utilization_rate * 100, { digits: 1 })}`}
              />
              <StatTile
                label="오늘 신청량"
                value={formatNumber(summary.data.applications_today)}
                unit="건"
                icon="📝"
                hint={`기준일 ${summary.data.as_of}`}
              />
              <StatTile
                label="AI 추천 거래"
                value={formatNumber(summary.data.ai_recommended_deals)}
                unit="건"
                icon="🤖"
                hint="추천 후 성사된 거래 기준"
              />
            </>
          )}
        </StatTileGrid>
        </div>
      )}

      {/* --- 유휴농지 등록 (SPEC 7.3 토지 소유자) --- */}
      {registered ? (
        <div data-testid="register-success">
          <AlertBanner tone="good" title="유휴농지가 등록되었습니다">
            {registered}
          </AlertBanner>
        </div>
      ) : null}
      {regions.status === 'success' ? (
        <ParcelRegisterForm
          regions={regions.data}
          onRegistered={(feature) => {
            setRegistered(
              `${feature.properties.name} · ${feature.properties.region_name} — 상태 ${feature.properties.status_label}. 아래 조건 비교에서 적합도를 확인할 수 있습니다.`,
            );
            setSelectedId(feature.properties.id);
            geo.reload();
            summary.reload();
            match.reload();
          }}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* --- 지도 --- */}
        <Card className="lg:col-span-2">
          <CardHeader
            title="유휴농지 지도"
            description="색으로 농지 상태를 구분한다. 마커를 누르면 조건과 상세 화면으로 이어진다."
            action={
              summary.status === 'success' && summary.data.region_name ? (
                <Badge tone="info">{summary.data.region_name}</Badge>
              ) : null
            }
          />
          <CardBody className="space-y-4">
            {geo.status === 'error' ? (
              <AlertBanner tone="bad" title="지도 데이터를 불러오지 못했습니다">
                {errorMessage(geo.error)}
              </AlertBanner>
            ) : geo.status === 'loading' ? (
              <Skeleton className="aspect-[4/3] w-full" />
            ) : features.length === 0 ? (
              <EmptyState
                icon="🗺️"
                title="이 지역에는 등록된 유휴농지가 없습니다"
                description="지역을 넓혀서 다시 찾아보세요."
              />
            ) : (
              <ParcelMap
                points={points}
                contextPoints={contextPoints}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            )}
            <ParcelMapLegend items={legendItems} />
          </CardBody>
        </Card>

        {/* --- 선택한 농지 --- */}
        <Card data-testid="parcel-detail-card">
          <CardHeader title={selected ? selected.properties.name : '농지 선택'} />
          <CardBody>
            {selected === null ? (
              <p className="text-sm text-ink-muted">
                지도에서 농지를 누르면 면적·임대료·토양 상태·주변 시설을 볼 수 있습니다.
              </p>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={CONDITION_STATUS[selected.properties.condition]} />
                  <Badge tone={STATUS_TONES[selected.properties.status]}>
                    {selected.properties.status_label}
                  </Badge>
                  <span className="text-sm text-ink-muted">{selected.properties.region_name}</span>
                </div>

                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <div>
                    <dt className="text-xs text-ink-muted">면적</dt>
                    <dd className="numeric mt-0.5">{formatPyeong(selected.properties.area_pyeong)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">월 임대료</dt>
                    <dd className="numeric mt-0.5">
                      {formatMoney(selected.properties.monthly_rent_krw)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">토양 상태</dt>
                    <dd className="mt-0.5">{selected.properties.soil_grade}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">농업용수</dt>
                    <dd className="mt-0.5">
                      {selected.properties.water_access ? '확보' : '미확보'}
                    </dd>
                  </div>
                </dl>

                <div className="flex flex-wrap gap-2">
                  <ButtonLink
                    href={parcelDetailHref(selected.properties.id)}
                    size="sm"
                    data-testid="open-parcel-detail"
                  >
                    상세 보기
                  </ButtonLink>
                  {selected.properties.status === 'idle' ? (
                    <button
                      type="button"
                      className="text-sm font-medium text-accent underline-offset-2 hover:underline"
                      data-testid={`apply-from-map-${selected.properties.id}`}
                      onClick={() =>
                        startApply(
                          selected.properties,
                          match.data?.results.find(
                            (result) => result.parcel_id === selected.properties.id,
                          )?.total_score,
                        )
                      }
                    >
                      임대 신청하기
                    </button>
                  ) : null}
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* --- 조건 비교 (SPEC 5.6) --- */}
      <Card>
        <CardHeader
          title="조건 비교"
          description="희망 작물·면적·예산을 넣으면 서버가 여섯 축 가중합으로 적합도 순위를 매긴다 (SPEC 5.6)."
        />
        <CardBody className="space-y-6">
          {crops.status === 'error' || regions.status === 'error' ? (
            <AlertBanner tone="bad" title="기준 데이터를 불러오지 못했습니다">
              {errorMessage(crops.error ?? regions.error)}
            </AlertBanner>
          ) : crops.status === 'loading' || regions.status === 'loading' ? (
            <SkeletonTable rows={2} cols={3} />
          ) : (
            <ParcelFilters
              values={values}
              crops={crops.data}
              regions={regions.data}
              soilGrades={soilGrades}
              onChange={setValues}
              onSubmit={runCompare}
              onReset={() => {
                setValues((current) => ({ cropId: current.cropId, ...DEFAULT_FILTERS }));
                setQuery(null);
                setApplyTarget(null);
                setApplied(null);
              }}
            />
          )}

          {applied ? (
            <div data-testid="apply-success">
              <AlertBanner tone="good" title="임대 신청이 접수되었습니다">
                {applied}
              </AlertBanner>
            </div>
          ) : null}

          {applyTarget ? (
            <ApplyForm
              target={applyTarget}
              cropId={values.cropId}
              cropName={cropName}
              onCancel={() => setApplyTarget(null)}
              onSubmitted={(response) => {
                setApplied(
                  `${applyTarget.name} · ${response.application.applicant_name} 님의 신청 (${response.application.lease_months}개월) — 필지 상태가 ${response.parcel_status_label} 로 바뀌었습니다.`,
                );
                setApplyTarget(null);
                geo.reload();
                summary.reload();
                match.reload();
              }}
            />
          ) : null}

          {match.status === 'error' ? (
            <AlertBanner tone="bad" title="적합도를 계산하지 못했습니다">
              {errorMessage(match.error)}
            </AlertBanner>
          ) : query === null ? (
            <p className="text-sm text-ink-muted">
              조건을 입력하고 <strong>조건 비교</strong> 를 누르면 농지별 적합도와 순위가 나옵니다.
            </p>
          ) : match.status === 'loading' || match.data === null ? (
            <SkeletonTable rows={5} cols={4} />
          ) : filteredResults.length === 0 ? (
            <EmptyState
              icon="🔍"
              title="조건에 맞는 농지가 없습니다"
              description="토양 상태·주변 시설 필터를 넓히거나 예산을 조정해 보세요."
            />
          ) : (
            <div data-testid="compare-table">
              <ParcelCompare
                results={filteredResults}
                weights={match.data.weights}
                cropName={match.data.crop_name}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onApply={(result) => startApply(result, result.total_score)}
              />
            </div>
          )}
        </CardBody>
      </Card>

      <p className="text-sm text-ink-muted">
        농지를 고르셨나요?{' '}
        <Link href="/" className="font-medium text-accent underline-offset-2 hover:underline">
          홈으로 돌아가기
        </Link>
      </p>
    </div>
  );
}
