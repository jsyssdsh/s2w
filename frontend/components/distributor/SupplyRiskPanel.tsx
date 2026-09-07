'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  getAlerts,
  getSupplyRisk,
  type Alert,
  type RiskTier,
  type SupplyRisk,
} from '@/lib/api';
import { useApi } from '@/lib/useApi';
import { formatDate, formatPercent, formatTon } from '@/lib/format';
import {
  AlertBanner,
  Badge,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Select,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  type BadgeTone,
} from '@/components/ui';
import { PanelState } from './PanelState';

/**
 * 수급 위험 알림 (SPEC 5.4).
 *
 * `GET /api/alerts` 가 지역의 활성 알림을 위험한 순으로 주고,
 * `GET /api/supply-risk` 가 고른 품목의 물량 내역과 대응 방안을 준다.
 * 표 두 개의 모양은 SPEC 5.4 활용 예시 그대로다 — 소급 분석 결과와
 * 초과 물량 대응 방안.
 */

/** 위험 단계가 배너·배지 색을 정한다 (SPEC 5.4 "위험 단계"). */
const TIER_TONE: Record<RiskTier, Exclude<BadgeTone, 'neutral'>> = {
  안정: 'good',
  주의: 'warn',
  위험: 'bad',
};

interface VolumeRow {
  label: string;
  kg: number;
  emphasis?: boolean;
}

function volumeRows(risk: SupplyRisk): VolumeRow[] {
  const v = risk.volumes;
  return [
    { label: '농가 출하 예정량', kg: v.farm_shipment_kg },
    { label: '도매처 기존 재고량', kg: v.wholesaler_inventory_kg },
    { label: '전체 공급량', kg: v.total_supply_kg, emphasis: true },
    { label: '판매처 구매 수요량', kg: v.buyer_demand_kg },
    { label: '예상 초과 공급량', kg: v.excess_supply_kg, emphasis: true },
  ];
}

export function SupplyRiskPanel({ regionId }: { regionId: number }) {
  const [cropId, setCropId] = useState<number | null>(null);

  const alerts = useApi<Alert[]>(
    useCallback(
      (options) => getAlerts({ region_id: regionId }, options),
      [regionId],
    ),
  );

  /** 기본 선택은 가장 위험한 알림의 품목 — 화면을 열자마자 문제부터 보인다. */
  const activeCropId = cropId ?? alerts.data?.[0]?.crop.id ?? null;

  const risk = useApi<SupplyRisk | null>(
    useCallback(
      (options) =>
        activeCropId === null
          ? Promise.resolve(null)
          : getSupplyRisk({ region_id: regionId, crop_id: activeCropId }, options),
      [regionId, activeCropId],
    ),
  );

  const cropOptions = useMemo(
    () =>
      (alerts.data ?? []).map((alert) => ({
        value: String(alert.crop.id),
        label: `${alert.crop.name} · ${alert.risk_tier}`,
      })),
    [alerts.data],
  );

  /** 배너는 고른 품목의 알림을 따라간다 — 표와 배너가 다른 품목을 가리키면 안 된다. */
  const headline =
    alerts.data?.find((alert) => alert.crop.id === activeCropId) ?? alerts.data?.[0];

  return (
    <Card data-testid="supply-risk-panel">
      <CardHeader
        title="수급 위험 알림"
        description="지역 출하 예정량·도매처 재고·판매처 수요를 견줘 공급 과잉을 조기에 알립니다 (SPEC 5.4)."
        action={
          cropOptions.length > 0 ? (
            <Select
              label="품목"
              options={cropOptions}
              value={activeCropId === null ? '' : String(activeCropId)}
              data-testid="supply-risk-crop"
              onChange={(event) => setCropId(Number(event.target.value))}
            />
          ) : undefined
        }
      />
      <CardBody className="space-y-4">
        {alerts.status === 'success' ? (
          headline ? (
            <div data-testid="supply-risk-banner" data-tier={headline.risk_tier}>
              <AlertBanner
                tone={TIER_TONE[headline.risk_tier]}
                title={`${headline.crop.name} 수급 위험 단계 ${headline.risk_tier}`}
              >
                {headline.headline}
              </AlertBanner>
            </div>
          ) : (
            <div data-testid="supply-risk-banner" data-tier="안정">
              <AlertBanner tone="good" title="활성 수급 위험 알림이 없습니다">
                이 지역의 모든 품목이 안정 단계입니다.
              </AlertBanner>
            </div>
          )
        ) : null}

        <PanelState
          state={risk}
          rows={6}
          cols={2}
          emptyTitle="분석할 품목이 없습니다"
          isEmpty={(data) => data === null}
        >
          {(data) =>
            data === null ? null : (
              <div className="grid gap-5 lg:grid-cols-2">
                {/* min-w-0 이 없으면 안의 표(min-width) 때문에 칸이 줄지 않는다 */}
                <div className="min-w-0">
                  <h3 className="mb-2 text-sm font-semibold">소급 분석 결과</h3>
                  <Table caption="지역 수급 물량 내역">
                    <THead>
                      <TR>
                        <TH>항목</TH>
                        <TH align="right">물량</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {volumeRows(data).map((row) => (
                        <TR key={row.label} data-testid="volume-row">
                          <TD className={row.emphasis ? 'font-semibold' : undefined}>
                            {row.label}
                          </TD>
                          <TD
                            align="right"
                            className={row.emphasis ? 'font-semibold' : undefined}
                          >
                            {formatTon(row.kg)}
                          </TD>
                        </TR>
                      ))}
                      <TR>
                        <TD className="font-semibold">위험 단계</TD>
                        <TD align="right">
                          <Badge tone={TIER_TONE[data.risk_tier]} dot>
                            {data.risk_tier}
                          </Badge>
                        </TD>
                      </TR>
                    </TBody>
                  </Table>
                </div>

                <div className="min-w-0">
                  <h3 className="mb-2 text-sm font-semibold">초과 물량 대응 방안</h3>
                  <Table caption="초과 물량 대응 방안과 처리 물량">
                    <THead>
                      <TR>
                        <TH>대응 방안</TH>
                        <TH align="right">처리 물량</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {data.mitigation.actions.map((action) => (
                        <TR key={action.channel} data-testid="mitigation-row">
                          <TD>
                            <span className="font-medium">{action.label}</span>
                            <span className="block text-xs text-ink-muted">
                              {action.detail}
                            </span>
                          </TD>
                          <TD align="right">{formatTon(action.qty_kg)}</TD>
                        </TR>
                      ))}
                      <TR>
                        <TD className="font-semibold">합계</TD>
                        <TD align="right" className="font-semibold">
                          {formatTon(data.mitigation.planned_kg)}
                        </TD>
                      </TR>
                      {data.mitigation.shortfall_kg > 0 ? (
                        <TR>
                          <TD className="text-warn">미해결 물량</TD>
                          <TD align="right" className="text-warn">
                            {formatTon(data.mitigation.shortfall_kg)}
                          </TD>
                        </TR>
                      ) : null}
                    </TBody>
                  </Table>
                </div>
              </div>
            )
          }
        </PanelState>
      </CardBody>
      {risk.status === 'success' && risk.data ? (
        <CardFooter>
          {risk.data.region.name} · {formatDate(risk.data.window.start)} ~{' '}
          {formatDate(risk.data.window.end)} · 초과 공급 비율{' '}
          {formatPercent(risk.data.excess_ratio * 100)}
        </CardFooter>
      ) : null}
    </Card>
  );
}
