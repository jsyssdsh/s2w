'use client';

import { cn } from '@/lib/cn';
import { Button, type SelectOption } from '@/components/ui';
import type { Crop, Region } from '@/lib/api';

/**
 * 조건 입력 · 필터 패널 (SPEC 4.4 "향후 수정 계획" — 농지별 면적, 임대료,
 * 토양 상태, 주변 시설 정보를 비교한 뒤 임대 신청까지).
 *
 * 두 종류가 섞여 있다:
 *
 * - **적합도 조건** (희망 작물·면적·예산·지역) — `POST /api/parcels/match` 로 가서
 *   서버가 순위를 매긴다. 여섯 축 가중합은 서버 한 곳에만 있다 (SPEC 5.6).
 * - **좁히기 필터** (토양 상태·농업용수·냉장창고) — 순위는 그대로 두고 목록과
 *   지도에서 대상만 줄인다. 서버 점수를 흉내 내지 않는다.
 */

export type ColdStorageFilter = 'all' | 'possible' | 'possible_or_limited';

export interface ParcelFilterValues {
  cropId: number;
  regionId: number | null;
  areaMinPyeong: number;
  areaMaxPyeong: number;
  /** 예산은 화면에서 만 원 단위로 받는다 (SPEC 5.6 표기: "65만 원") */
  budgetManWon: number;
  soilGrade: string;
  waterOnly: boolean;
  coldStorage: ColdStorageFilter;
}

export const ALL = 'all';

/** SPEC 5.6 활용 예시 — 딸기 700~1,000평 / 예산 70만 원 */
export const DEFAULT_FILTERS: Omit<ParcelFilterValues, 'cropId'> = {
  regionId: null,
  areaMinPyeong: 700,
  areaMaxPyeong: 1000,
  budgetManWon: 70,
  soilGrade: ALL,
  waterOnly: false,
  coldStorage: ALL,
};

const COLD_STORAGE_OPTIONS: SelectOption[] = [
  { value: ALL, label: '전체' },
  { value: 'possible_or_limited', label: '가능 · 제한적' },
  { value: 'possible', label: '가능만' },
];

const FIELD =
  'h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink transition-colors hover:bg-surface-muted';

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-muted">
        {label}
      </label>
      <div className="mt-1">{children}</div>
      {hint ? <p className="mt-1 text-[11px] text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export function ParcelFilters({
  values,
  crops,
  regions,
  soilGrades,
  onChange,
  onSubmit,
  onReset,
  className,
}: {
  values: ParcelFilterValues;
  crops: readonly Crop[];
  regions: readonly Region[];
  /** 지도에 실제로 있는 토양 등급만 고를 수 있게 한다 */
  soilGrades: readonly string[];
  onChange: (values: ParcelFilterValues) => void;
  onSubmit: () => void;
  onReset: () => void;
  className?: string;
}) {
  const set = <K extends keyof ParcelFilterValues>(key: K, value: ParcelFilterValues[K]) =>
    onChange({ ...values, [key]: value });

  return (
    <form
      data-testid="parcel-filters"
      className={cn('grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3', className)}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Field label="희망 작물" htmlFor="filter-crop">
        <select
          id="filter-crop"
          data-testid="filter-crop"
          className={FIELD}
          value={values.cropId ? String(values.cropId) : ''}
          onChange={(event) => set('cropId', Number(event.target.value))}
        >
          {crops.map((crop) => (
            <option key={crop.id} value={crop.id}>
              {crop.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label="지역" htmlFor="filter-region">
        <select
          id="filter-region"
          data-testid="filter-region"
          className={FIELD}
          value={values.regionId === null ? ALL : String(values.regionId)}
          onChange={(event) =>
            set('regionId', event.target.value === ALL ? null : Number(event.target.value))
          }
        >
          <option value={ALL}>전체 지역</option>
          {regions.map((region) => (
            <option key={region.id} value={region.id}>
              {region.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label="희망 면적 (평)" htmlFor="filter-area-min" hint="최소 ~ 최대 범위 안이면 만점">
        <div className="flex items-center gap-2">
          <input
            id="filter-area-min"
            data-testid="filter-area-min"
            type="number"
            min={1}
            step="any"
            className={cn(FIELD, 'numeric')}
            value={values.areaMinPyeong}
            onChange={(event) => set('areaMinPyeong', Number(event.target.value))}
          />
          <span aria-hidden className="text-ink-muted">
            ~
          </span>
          <input
            aria-label="최대 면적 (평)"
            data-testid="filter-area-max"
            type="number"
            min={1}
            step="any"
            className={cn(FIELD, 'numeric')}
            value={values.areaMaxPyeong}
            onChange={(event) => set('areaMaxPyeong', Number(event.target.value))}
          />
        </div>
      </Field>

      <Field label="월 임대료 예산 (만 원)" htmlFor="filter-budget" hint="예산을 넘는 농지는 임대료 점수 0점">
        <input
          id="filter-budget"
          data-testid="filter-budget"
          type="number"
          min={1}
          step="any"
          className={cn(FIELD, 'numeric')}
          value={values.budgetManWon}
          onChange={(event) => set('budgetManWon', Number(event.target.value))}
        />
      </Field>

      <Field label="토양 상태" htmlFor="filter-soil">
        <select
          id="filter-soil"
          data-testid="filter-soil"
          className={FIELD}
          value={values.soilGrade}
          onChange={(event) => set('soilGrade', event.target.value)}
        >
          <option value={ALL}>전체</option>
          {soilGrades.map((grade) => (
            <option key={grade} value={grade}>
              {grade}
            </option>
          ))}
        </select>
      </Field>

      <Field label="주변 시설 — 냉장창고" htmlFor="filter-cold">
        <select
          id="filter-cold"
          data-testid="filter-cold"
          className={FIELD}
          value={values.coldStorage}
          onChange={(event) => set('coldStorage', event.target.value as ColdStorageFilter)}
        >
          {COLD_STORAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </Field>

      <div className="flex flex-wrap items-center justify-between gap-3 sm:col-span-2 lg:col-span-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            data-testid="filter-water"
            className="size-4 rounded border-line-strong accent-[var(--color-accent)]"
            checked={values.waterOnly}
            onChange={(event) => set('waterOnly', event.target.checked)}
          />
          농업용수 확보된 농지만
        </label>

        <div className="flex items-center gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onReset}>
            초기화
          </Button>
          <Button type="submit" data-testid="compare-submit">
            조건 비교
          </Button>
        </div>
      </div>
    </form>
  );
}

/** 좁히기 필터를 적용한다 — 서버가 매긴 순위는 건드리지 않는다. */
export function passesFilters(
  parcel: { soil_grade: string; water_access: boolean; cold_storage_access: string },
  values: ParcelFilterValues,
): boolean {
  if (values.soilGrade !== ALL && parcel.soil_grade !== values.soilGrade) return false;
  if (values.waterOnly && !parcel.water_access) return false;
  if (values.coldStorage === 'possible' && parcel.cold_storage_access !== 'possible') return false;
  if (
    values.coldStorage === 'possible_or_limited' &&
    parcel.cold_storage_access !== 'possible' &&
    parcel.cold_storage_access !== 'limited'
  ) {
    return false;
  }
  return true;
}
