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
  type Deal,
  type DealStatus,
  type Shipment,
  type Wholesaler,
} from '@/lib/api';
import { formatDate, formatKg, formatMoney } from '@/lib/format';

/** SPEC 7.1 거래 상태 표기 — 서버의 `status_label` 과 같은 문구를 쓴다. */
const STATUS_LABEL: Record<DealStatus, string> = {
  proposed: '추천 제시',
  accepted: '거래 수락',
  rejected: '거래 거절',
  settled: '정산 완료',
};

const STATUS_TONE: Record<DealStatus, 'good' | 'warn' | 'bad' | 'info' | 'neutral'> = {
  proposed: 'info',
  accepted: 'good',
  rejected: 'bad',
  settled: 'good',
};

/**
 * 빠른 기능 ④ 거래 현황 (SPEC 4.2 / 7.1).
 *
 * `GET /api/deals` 가 거래 원장이고, 출하와 도매처 이름은 각각
 * `/api/shipments` · `/api/wholesalers` 에서 붙인다 — 이 농가의 출하에 붙은
 * 거래만 남긴다.
 */
export function DealHistoryPanel({
  deals,
  shipments,
  wholesalers,
}: {
  deals: AsyncState<Deal[]>;
  shipments: AsyncState<Shipment[]>;
  wholesalers: AsyncState<Wholesaler[]>;
}) {
  const loading =
    deals.status === 'loading' ||
    shipments.status === 'loading' ||
    wholesalers.status === 'loading';
  const error = deals.error ?? shipments.error ?? wholesalers.error;

  const shipmentById = new Map(
    (shipments.data ?? []).map((shipment) => [shipment.shipment_id, shipment]),
  );
  const wholesalerName = new Map((wholesalers.data ?? []).map((w) => [w.id, w.name]));
  const rows = (deals.data ?? [])
    .filter((deal) => shipmentById.has(deal.shipment_id))
    .sort((a, b) => b.id - a.id);

  return (
    <Card data-testid="deal-history">
      <CardHeader
        title="거래 현황"
        description="AI 추천에서 선택한 거래가 여기에 쌓이고, 다음 추천의 학습 신호가 됩니다."
      />
      <CardBody>
        {loading ? (
          <SkeletonTable rows={3} cols={5} />
        ) : error ? (
          <AlertBanner tone="bad">{errorMessage(error)}</AlertBanner>
        ) : rows.length === 0 ? (
          <EmptyState
            title="아직 거래가 없습니다"
            description="AI 유통 추천에서 도매처를 선택하면 거래 현황에 기록됩니다."
          />
        ) : (
          <Table caption="출하별 거래 도매처와 계약 금액, 진행 상태">
            <THead>
              <TR>
                <TH>출하</TH>
                <TH>도매처</TH>
                <TH align="right">계약 금액</TH>
                <TH align="center">상태</TH>
                <TH align="right">결정일</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((deal) => {
                const shipment = shipmentById.get(deal.shipment_id)!;
                return (
                  <TR key={deal.id}>
                    <TD>
                      <p className="font-medium">
                        {`${shipment.crop_name} ${formatKg(shipment.qty_kg)}`}
                      </p>
                      <p className="mt-0.5 text-xs text-ink-muted">
                        {`${formatDate(shipment.ship_date)} 출하 · ${shipment.grade_label}`}
                      </p>
                    </TD>
                    <TD>{wholesalerName.get(deal.wholesaler_id) ?? `도매처 ${deal.wholesaler_id}`}</TD>
                    <TD align="right">{formatMoney(deal.agreed_price_krw)}</TD>
                    <TD align="center">
                      <Badge tone={STATUS_TONE[deal.status]}>{STATUS_LABEL[deal.status]}</Badge>
                    </TD>
                    <TD align="right">{deal.decided_on ? formatDate(deal.decided_on) : '—'}</TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </CardBody>
    </Card>
  );
}
