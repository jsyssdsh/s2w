'use client';

import {
  AlertBanner,
  Badge,
  Button,
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
  type Shipment,
  type WholesalerRecommendation,
} from '@/lib/api';
import { formatDate, formatKg, formatMoney, formatWonPerKg } from '@/lib/format';

/**
 * 빠른 기능 ② AI 유통 추천 (SPEC 5.2).
 *
 * 표의 열은 SPEC 5.2 활용 예시 그대로다 —
 * 도매처 / 매입단가 / 구매량 / 운송비 / 예상 순수익 / 순위.
 * 행마다 서버가 만든 한국어 추천 근거를 붙이고, 1위 도매처가 물량을 다 받지
 * 못하면 응답의 `notes` 경고를 위에 띄운다.
 */
export function WholesalerRecommendationPanel({
  shipment,
  recommendation,
  selectedWholesalerId,
  pendingWholesalerId,
  dealError,
  onSelect,
}: {
  shipment: Shipment | null;
  recommendation: AsyncState<WholesalerRecommendation>;
  /** 이미 거래로 확정한 도매처 */
  selectedWholesalerId: number | null;
  pendingWholesalerId: number | null;
  dealError: unknown;
  onSelect: (wholesalerId: number) => void;
}) {
  return (
    <Card data-testid="wholesaler-recommendation">
      <CardHeader
        title="AI 유통 추천"
        description={
          shipment
            ? `${formatDate(shipment.ship_date)} 출하 · ${shipment.crop_name} ${formatKg(shipment.qty_kg)} 기준 도매처별 예상 순수익`
            : '출하를 등록하면 도매처별 예상 순수익을 계산합니다.'
        }
      />
      <CardBody>
        {!shipment ? (
          <EmptyState
            title="등록된 출하가 없습니다"
            description="작물 등록에서 출하 예정을 먼저 남겨 주세요. (SPEC 5.2)"
          />
        ) : recommendation.status === 'loading' ? (
          <SkeletonTable rows={3} cols={6} />
        ) : recommendation.status === 'error' ? (
          <AlertBanner tone="bad">{errorMessage(recommendation.error)}</AlertBanner>
        ) : recommendation.data.candidates.length === 0 ? (
          <EmptyState
            title="추천할 도매처가 없습니다"
            description="등록된 도매처가 없어 순수익을 비교할 수 없습니다."
          />
        ) : (
          <Body
            recommendation={recommendation.data}
            selectedWholesalerId={selectedWholesalerId}
            pendingWholesalerId={pendingWholesalerId}
            dealError={dealError}
            onSelect={onSelect}
          />
        )}
      </CardBody>
    </Card>
  );
}

function Body({
  recommendation,
  selectedWholesalerId,
  pendingWholesalerId,
  dealError,
  onSelect,
}: {
  recommendation: WholesalerRecommendation;
  selectedWholesalerId: number | null;
  pendingWholesalerId: number | null;
  dealError: unknown;
  onSelect: (wholesalerId: number) => void;
}) {
  return (
    <div className="space-y-4">
      {recommendation.notes.map((note) => (
        <AlertBanner key={note} tone="warn">
          {note}
        </AlertBanner>
      ))}
      {dealError ? <AlertBanner tone="bad">{errorMessage(dealError)}</AlertBanner> : null}

      <Table caption="도매처별 매입단가·구매량·운송비와 예상 순수익 비교">
        <THead>
          <TR>
            <TH>도매처</TH>
            <TH align="right">매입단가</TH>
            <TH align="right">구매량</TH>
            <TH align="right">운송비</TH>
            <TH align="right">예상 순수익</TH>
            <TH align="center">순위</TH>
            <TH align="center">거래</TH>
          </TR>
        </THead>
        <TBody>
          {recommendation.candidates.map((candidate) => {
            const chosen = candidate.wholesaler_id === selectedWholesalerId;
            return (
              <TR key={candidate.wholesaler_id} data-testid={`candidate-${candidate.rank}`}>
                <TD>
                  <p className="font-medium">{candidate.name}</p>
                  <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                    {candidate.reason}
                  </p>
                </TD>
                <TD align="right">{formatWonPerKg(candidate.unit_price_krw)}</TD>
                <TD align="right">
                  {formatKg(candidate.sellable_kg)}
                  {candidate.unsold_kg > 0 ? (
                    <span className="block text-xs text-bad">
                      {formatKg(candidate.unsold_kg)} 잔여
                    </span>
                  ) : null}
                </TD>
                <TD align="right">{formatMoney(candidate.transport_cost_krw)}</TD>
                <TD align="right" className="font-semibold">
                  {formatMoney(candidate.net_profit_krw)}
                </TD>
                <TD align="center">
                  <Badge tone={candidate.rank === 1 ? 'good' : 'neutral'}>
                    {`${candidate.rank}위`}
                  </Badge>
                </TD>
                <TD align="center">
                  {chosen ? (
                    <Badge tone="info">선택 완료</Badge>
                  ) : (
                    <Button
                      size="sm"
                      variant={candidate.rank === 1 ? 'primary' : 'secondary'}
                      disabled={pendingWholesalerId !== null}
                      onClick={() => onSelect(candidate.wholesaler_id)}
                    >
                      {pendingWholesalerId === candidate.wholesaler_id ? '기록 중…' : '이 도매처 선택'}
                    </Button>
                  )}
                </TD>
              </TR>
            );
          })}
        </TBody>
      </Table>
    </div>
  );
}
