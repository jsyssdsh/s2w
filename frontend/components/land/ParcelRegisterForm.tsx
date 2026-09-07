'use client';

import { useState } from 'react';
import { AlertBanner, Button, Card, CardBody, CardHeader } from '@/components/ui';
import { cn } from '@/lib/cn';
import {
  errorMessage,
  registerParcel,
  type ColdStorageAccess,
  type ParcelFeature,
  type Region,
} from '@/lib/api';

/**
 * 유휴농지 등록 (SPEC 7.3 "토지 소유자 — 유휴농지 발생 등록").
 *
 * SPEC 7.3 흐름의 **첫 단계**다. 여기서 등록한 필지는 유휴 상태로 지도에
 * 올라가고, 곧바로 아래 조건 비교(적합도 분석)의 후보가 되며, 농가가 매칭을
 * 신청하면 운영 중으로 넘어간다.
 *
 * 좌표는 받지 않는다 — 소유자가 위경도를 알 이유가 없어서, 서버가 시군구
 * 중심을 넣는다. 상태도 받지 않는다: 등록은 언제나 유휴로 시작한다.
 */

const FIELD = 'h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink';

const COLD_STORAGE_OPTIONS: { value: ColdStorageAccess; label: string }[] = [
  { value: 'possible', label: '가능' },
  { value: 'limited', label: '제한적' },
  { value: 'none', label: '미확보' },
];

const SOIL_OPTIONS = ['1등급', '2등급', '3등급'];

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-muted">
        {label}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

export function ParcelRegisterForm({
  regions,
  onRegistered,
  className,
}: {
  regions: Region[];
  onRegistered: (feature: ParcelFeature) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [regionId, setRegionId] = useState<number>(regions[0]?.id ?? 0);
  const [areaPyeong, setAreaPyeong] = useState(900);
  const [rentManWon, setRentManWon] = useState(60);
  const [waterAccess, setWaterAccess] = useState(true);
  const [coldStorage, setColdStorage] = useState<ColdStorageAccess>('limited');
  const [soilGrade, setSoilGrade] = useState('2등급');
  const [ownerName, setOwnerName] = useState('');
  const [ownerPhone, setOwnerPhone] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const feature = await registerParcel({
        name,
        region_id: regionId,
        area_pyeong: areaPyeong,
        // 화면은 SPEC 5.6 표기대로 만 원 단위로 받고, API 는 원 단위다.
        monthly_rent_krw: rentManWon * 10_000,
        water_access: waterAccess,
        cold_storage_access: coldStorage,
        soil_grade: soilGrade,
        owner_name: ownerName || null,
        owner_phone: ownerPhone || null,
      });
      setName('');
      setOwnerName('');
      setOwnerPhone('');
      setOpen(false);
      onRegistered(feature);
    } catch (cause) {
      setError(cause);
    } finally {
      setPending(false);
    }
  }

  if (!open) {
    return (
      <div className={className}>
        <Button
          type="button"
          variant="secondary"
          data-testid="register-parcel-open"
          onClick={() => setOpen(true)}
        >
          유휴농지 등록
        </Button>
      </div>
    );
  }

  return (
    <Card className={cn('border-accent/40', className)} data-testid="register-parcel-form">
      <CardHeader
        title="유휴농지 등록"
        description="토지 소유자가 위치·면적·용수·임대 조건을 올리면 유휴 상태로 지도에 표시되고, 바로 아래 조건 비교의 후보가 됩니다. (SPEC 7.3)"
      />
      <CardBody>
        <form className="grid grid-cols-1 gap-4 sm:grid-cols-2" onSubmit={submit}>
          <Field label="농지 이름" htmlFor="register-name">
            <input
              id="register-name"
              data-testid="register-name"
              className={FIELD}
              required
              maxLength={64}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>

          <Field label="지역" htmlFor="register-region">
            <select
              id="register-region"
              data-testid="register-region"
              className={FIELD}
              value={regionId}
              onChange={(event) => setRegionId(Number(event.target.value))}
            >
              {regions.map((region) => (
                <option key={region.id} value={region.id}>
                  {region.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="면적 (평)" htmlFor="register-area">
            <input
              id="register-area"
              data-testid="register-area"
              type="number"
              min={1}
              className={cn(FIELD, 'numeric')}
              value={areaPyeong}
              onChange={(event) => setAreaPyeong(Number(event.target.value))}
            />
          </Field>

          <Field label="월 임대료 (만 원)" htmlFor="register-rent">
            <input
              id="register-rent"
              data-testid="register-rent"
              type="number"
              min={1}
              className={cn(FIELD, 'numeric')}
              value={rentManWon}
              onChange={(event) => setRentManWon(Number(event.target.value))}
            />
          </Field>

          <Field label="토양 상태" htmlFor="register-soil">
            <select
              id="register-soil"
              data-testid="register-soil"
              className={FIELD}
              value={soilGrade}
              onChange={(event) => setSoilGrade(event.target.value)}
            >
              {SOIL_OPTIONS.map((grade) => (
                <option key={grade} value={grade}>
                  {grade}
                </option>
              ))}
            </select>
          </Field>

          <Field label="냉장창고 접근성" htmlFor="register-cold">
            <select
              id="register-cold"
              data-testid="register-cold"
              className={FIELD}
              value={coldStorage}
              onChange={(event) => setColdStorage(event.target.value as ColdStorageAccess)}
            >
              {COLD_STORAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="토지 소유자명" htmlFor="register-owner">
            <input
              id="register-owner"
              data-testid="register-owner"
              className={FIELD}
              maxLength={64}
              value={ownerName}
              onChange={(event) => setOwnerName(event.target.value)}
            />
          </Field>

          <Field label="연락처" htmlFor="register-phone">
            <input
              id="register-phone"
              className={FIELD}
              maxLength={32}
              value={ownerPhone}
              onChange={(event) => setOwnerPhone(event.target.value)}
            />
          </Field>

          <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2">
            <input
              type="checkbox"
              data-testid="register-water"
              className="size-4 rounded border-line-strong"
              checked={waterAccess}
              onChange={(event) => setWaterAccess(event.target.checked)}
            />
            농업용수 확보
          </label>

          {error ? (
            <div className="sm:col-span-2">
              <AlertBanner tone="bad" title="농지를 등록하지 못했습니다">
                {errorMessage(error)}
              </AlertBanner>
            </div>
          ) : null}

          <div className="flex items-center justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              취소
            </Button>
            <Button type="submit" data-testid="register-submit" disabled={pending}>
              {pending ? '등록 중…' : '농지 등록'}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
