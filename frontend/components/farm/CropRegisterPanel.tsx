'use client';

import { useState } from 'react';
import { AlertBanner, Button, Card, CardBody, CardHeader, Select } from '@/components/ui';
import {
  GRADE_OPTIONS,
  createShipment,
  errorMessage,
  type Crop,
  type Farm,
  type Grade,
  type Shipment,
} from '@/lib/api';
import { formatDate, formatKg } from '@/lib/format';

/**
 * 빠른 기능 ① 작물 등록 (SPEC 4.2).
 *
 * 품목 · 출하량 · 출하 예정일 · 등급을 받아 `POST /api/farms/{id}/shipments`
 * 로 출하를 만든다. 등록된 출하가 곧바로 AI 유통 추천의 대상이 된다.
 */
export function CropRegisterPanel({
  farm,
  crops,
  defaultShipDate,
  onCreated,
}: {
  farm: Farm;
  crops: Crop[];
  /** 기본 출하 예정일 — 시세 이력의 기준일을 그대로 쓴다 (벽시계 미사용) */
  defaultShipDate: string;
  onCreated: (shipment: Shipment) => void;
}) {
  const [cropId, setCropId] = useState<string>(
    String(farm.crops[0]?.crop_id ?? crops[0]?.id ?? ''),
  );
  const [qty, setQty] = useState('1000');
  const [shipDate, setShipDate] = useState(defaultShipDate);
  const [grade, setGrade] = useState<Grade>('special');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<Shipment | null>(null);

  const qtyKg = Number(qty);
  const valid = Boolean(cropId) && Number.isFinite(qtyKg) && qtyKg > 0 && Boolean(shipDate);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || pending) return;
    setPending(true);
    setError(null);
    try {
      const shipment = await createShipment(farm.farm_id, {
        crop_id: Number(cropId),
        qty_kg: qtyKg,
        ship_date: shipDate,
        grade,
      });
      setDone(shipment);
      onCreated(shipment);
    } catch (cause) {
      setError(cause);
    } finally {
      setPending(false);
    }
  }

  return (
    <Card data-testid="crop-register">
      <CardHeader
        title="작물 등록"
        description="출하 예정을 등록하면 AI 유통 추천과 가격 분석이 이 출하를 기준으로 계산됩니다."
      />
      <CardBody>
        <form className="grid grid-cols-1 gap-4 sm:grid-cols-2" onSubmit={submit}>
          <Select
            label="품목"
            data-testid="register-crop"
            className="flex-col items-start gap-1.5 sm:flex-row sm:items-center"
            value={cropId}
            onChange={(event) => setCropId(event.target.value)}
            options={crops.map((crop) => ({ value: String(crop.id), label: crop.name }))}
          />
          <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-center sm:gap-2">
            <label htmlFor="register-qty" className="text-sm whitespace-nowrap text-ink-muted">
              출하량 (kg)
            </label>
            <input
              id="register-qty"
              data-testid="register-qty"
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={qty}
              onChange={(event) => setQty(event.target.value)}
              className="numeric h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink sm:w-32"
            />
          </div>
          <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-center sm:gap-2">
            <label htmlFor="register-date" className="text-sm whitespace-nowrap text-ink-muted">
              출하 예정일
            </label>
            <input
              id="register-date"
              data-testid="register-date"
              type="date"
              value={shipDate}
              onChange={(event) => setShipDate(event.target.value)}
              className="h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink sm:w-44"
            />
          </div>
          <Select
            label="등급"
            data-testid="register-grade"
            className="flex-col items-start gap-1.5 sm:flex-row sm:items-center"
            value={grade}
            onChange={(event) => setGrade(event.target.value as Grade)}
            options={GRADE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
          />
          <div className="sm:col-span-2">
            <Button type="submit" data-testid="register-submit" disabled={!valid || pending}>
              {pending ? '등록 중…' : '작물 등록'}
            </Button>
          </div>
        </form>

        {error ? (
          <AlertBanner tone="bad" className="mt-4">
            {errorMessage(error)}
          </AlertBanner>
        ) : null}
        {done && !error ? (
          <AlertBanner tone="good" className="mt-4" data-testid="register-done">
            {`${formatDate(done.ship_date)} 출하 · ${done.crop_name} ${formatKg(done.qty_kg)} (${done.grade_label}) 등록을 마쳤습니다.`}
          </AlertBanner>
        ) : null}
      </CardBody>
    </Card>
  );
}
