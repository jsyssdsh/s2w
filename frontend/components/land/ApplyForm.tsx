'use client';

import { useState } from 'react';
import { AlertBanner, Button, Card, CardBody, CardHeader } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatMoney, formatPercent, formatPyeong } from '@/lib/format';
import { applyForParcel, errorMessage, type ParcelApplicationResponse } from '@/lib/api';

/**
 * 임대(매칭) 신청 (SPEC 7.3 "농가가 매칭을 신청해 스마트팜 재배로 연결").
 *
 * 접수되면 서버가 필지를 유휴 → 운영 중으로 넘기고 그 결과를 응답에 실어 준다.
 * 화면은 그 값을 그대로 써서 지도·요약 지표를 다시 불러온다.
 */

export interface ApplyTarget {
  parcelId: number;
  name: string;
  areaPyeong: number;
  monthlyRentKrw: number;
  matchScore?: number | null;
}

const FIELD =
  'h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-sm text-ink';

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

export function ApplyForm({
  target,
  cropId,
  cropName,
  onSubmitted,
  onCancel,
  className,
}: {
  target: ApplyTarget;
  cropId: number;
  cropName: string;
  onSubmitted: (response: ParcelApplicationResponse) => void;
  onCancel: () => void;
  className?: string;
}) {
  const [applicantName, setApplicantName] = useState('김청년');
  const [phone, setPhone] = useState('010-1000-0001');
  const [leaseMonths, setLeaseMonths] = useState(24);
  const [message, setMessage] = useState(`${cropName} 스마트팜을 조성하고 싶습니다.`);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await applyForParcel(target.parcelId, {
        crop_id: cropId,
        applicant_name: applicantName,
        phone: phone || null,
        lease_months: leaseMonths,
        message,
        match_score: target.matchScore ?? null,
      });
      onSubmitted(response);
    } catch (cause) {
      setError(cause);
    } finally {
      setPending(false);
    }
  }

  return (
    <Card className={cn('border-accent/40', className)} data-testid="apply-form">
      <CardHeader
        title={`${target.name} 임대 신청`}
        description={`${formatPyeong(target.areaPyeong)} · 월 ${formatMoney(target.monthlyRentKrw)}${
          target.matchScore != null
            ? ` · 적합도 ${formatPercent(target.matchScore * 100, { digits: 1 })}`
            : ''
        }`}
      />
      <CardBody>
        <form className="grid grid-cols-1 gap-4 sm:grid-cols-2" onSubmit={submit}>
          <Field label="재배 작물" htmlFor="apply-crop">
            <input id="apply-crop" className={cn(FIELD, 'bg-surface-muted')} value={cropName} readOnly />
          </Field>

          <Field label="신청 농가명" htmlFor="apply-name">
            <input
              id="apply-name"
              data-testid="apply-name"
              className={FIELD}
              required
              maxLength={64}
              value={applicantName}
              onChange={(event) => setApplicantName(event.target.value)}
            />
          </Field>

          <Field label="연락처" htmlFor="apply-phone">
            <input
              id="apply-phone"
              className={FIELD}
              maxLength={32}
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
            />
          </Field>

          <Field label="희망 임대 기간 (개월)" htmlFor="apply-months">
            <input
              id="apply-months"
              type="number"
              min={1}
              max={120}
              className={cn(FIELD, 'numeric')}
              value={leaseMonths}
              onChange={(event) => setLeaseMonths(Number(event.target.value))}
            />
          </Field>

          <div className="sm:col-span-2">
            <Field label="메시지" htmlFor="apply-message">
              <textarea
                id="apply-message"
                rows={2}
                maxLength={255}
                className={cn(FIELD, 'h-auto py-2')}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
              />
            </Field>
          </div>

          {error ? (
            <div className="sm:col-span-2">
              <AlertBanner tone="bad" title="신청을 접수하지 못했습니다">
                {errorMessage(error)}
              </AlertBanner>
            </div>
          ) : null}

          <div className="flex items-center justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="secondary" onClick={onCancel}>
              취소
            </Button>
            <Button type="submit" data-testid="apply-submit" disabled={pending}>
              {pending ? '접수 중…' : '신청 접수'}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
