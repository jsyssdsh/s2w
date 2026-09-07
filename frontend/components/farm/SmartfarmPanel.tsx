'use client';

import {
  AlertBanner,
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  SkeletonTable,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui';
import {
  errorMessage,
  type AsyncState,
  type ControlDevice,
  type SmartfarmStatus,
} from '@/lib/api';
import { formatDate } from '@/lib/format';

/** SPEC 5.5 구동장치의 한국어 이름. */
export const DEVICE_LABEL: Record<ControlDevice, string> = {
  pump: '워터펌프',
  fan: '환기팬',
  light: '조명',
};

const ACTION_LABEL: Record<string, string> = { on: '가동 중', off: '정지' };

/** "2026-08-08T23:00:00" → "2026년 8월 8일 23:00" */
function formatMeasuredAt(ts: string | null): string {
  if (!ts) return '측정값 없음';
  const [day, time] = ts.split('T');
  return `${formatDate(day)} ${time?.slice(0, 5) ?? ''} 측정`.trim();
}

/**
 * 스마트팜 상태 패널 (SPEC 4.2) — 온도 / 습도 / 조도 / 워터펌프 상태.
 *
 * 표는 SPEC 5.5 그대로 적정 기준과 현재 값을 나란히 두고, 범위 안팎을
 * 배지로 구분한다. 워터펌프를 포함한 장치 상태는 `devices` 에서 온다.
 */
export function SmartfarmPanel({ status }: { status: AsyncState<SmartfarmStatus> }) {
  return (
    <Card data-testid="smartfarm-panel">
      <CardHeader
        title="스마트팜 상태"
        description={
          status.status === 'success'
            ? `${status.data.name} · ${status.data.type} — ${formatMeasuredAt(status.data.ts)}`
            : '온도 · 습도 · 조도 · 워터펌프 상태를 적정 기준과 비교합니다.'
        }
      />
      <CardBody>
        {status.status === 'loading' ? (
          <SkeletonTable rows={4} cols={4} />
        ) : status.status === 'error' ? (
          <AlertBanner tone="bad">{errorMessage(status.error)}</AlertBanner>
        ) : status.data.metrics.length === 0 ? (
          <EmptyState
            title="측정값이 없습니다"
            description="센서가 아직 값을 보내지 않았습니다. (SPEC 5.5)"
          />
        ) : (
          <div className="space-y-4">
            <Table caption="측정 항목별 적정 기준과 현재 값, 자동제어 결과">
              <THead>
                <TR>
                  <TH>측정 항목</TH>
                  <TH align="right">적정 기준</TH>
                  <TH align="right">현재 상태</TH>
                  <TH align="center">범위</TH>
                  <TH>자동제어 결과</TH>
                </TR>
              </THead>
              <TBody>
                {status.data.metrics.map((metric) => (
                  <TR key={metric.metric}>
                    <TD className="font-medium">{metric.label}</TD>
                    <TD align="right">{metric.target_display}</TD>
                    <TD align="right" className="font-semibold">{metric.display}</TD>
                    <TD align="center">
                      <Badge tone={metric.in_range ? 'good' : 'bad'} dot>
                        {metric.in_range ? '적정' : '범위 이탈'}
                      </Badge>
                    </TD>
                    <TD>{metric.control_display}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>

            <div
              data-testid="smartfarm-devices"
              className="flex flex-wrap gap-2 border-t border-line pt-4"
            >
              {status.data.devices.map((device) => (
                <Badge
                  key={device.device}
                  tone={device.action === 'on' ? 'warn' : 'neutral'}
                  dot
                >
                  {`${DEVICE_LABEL[device.device]} ${ACTION_LABEL[device.action] ?? device.action}`}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
