'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  getWholesalerInventory,
  matchBuyers,
  type BuyerMatchResponse,
  type InventoryLot,
} from '@/lib/api';
import { useApi } from '@/lib/useApi';
import { formatDate, formatKg, formatKm } from '@/lib/format';
import { cn } from '@/lib/cn';
import {
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
} from '@/components/ui';
import { PanelState } from './PanelState';

/**
 * 판매처 연계 패널 (SPEC 5.3).
 *
 * SPEC 5.3 활용 예시의 표 모양 그대로다 — 보유 농산물 / 주요 상태 /
 * 추천 판매처. 재고는 `GET /api/wholesalers/{id}/inventory`, 추천은
 * `POST /api/recommendations/buyers` 에서 온다. 판매기한이 임박한 로트는
 * 색과 글자를 함께 써서 눈에 띄게 한다.
 */
export function BuyerLinkPanel({ wholesalerId }: { wholesalerId: number }) {
  const [cropId, setCropId] = useState<number | null>(null);

  const inventory = useApi<InventoryLot[]>(
    useCallback(
      (options) => getWholesalerInventory(wholesalerId, undefined, options),
      [wholesalerId],
    ),
  );

  /** 재고가 있는 품목만 고르게 한다. 기본값은 판매기한이 가장 급한 로트의 품목. */
  const cropOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const lot of inventory.data ?? []) seen.set(lot.crop_id, lot.crop_name);
    return [...seen].map(([id, name]) => ({ value: String(id), label: name }));
  }, [inventory.data]);

  const activeCropId = cropId ?? inventory.data?.[0]?.crop_id ?? null;

  const matches = useApi<BuyerMatchResponse | null>(
    useCallback(
      (options) =>
        activeCropId === null
          ? Promise.resolve(null)
          : matchBuyers({ wholesaler_id: wholesalerId, crop_id: activeCropId }, options),
      [wholesalerId, activeCropId],
    ),
  );

  return (
    <Card data-testid="buyer-link-panel">
      <CardHeader
        title="판매처 연계"
        description="보유 재고를 등급·판매기한으로 나눠 적합한 판매처를 연결합니다 (SPEC 5.3)."
        action={
          cropOptions.length > 0 ? (
            <Select
              label="품목"
              options={cropOptions}
              value={activeCropId === null ? '' : String(activeCropId)}
              data-testid="buyer-link-crop"
              onChange={(event) => setCropId(Number(event.target.value))}
            />
          ) : undefined
        }
      />
      <CardBody className="px-0 py-0">
        <PanelState
          state={matches}
          rows={4}
          cols={3}
          emptyTitle="보유 재고가 없습니다"
          emptyDescription="이 도매처에는 연계할 재고 로트가 없습니다."
          isEmpty={(data) => data === null || data.lots.length === 0}
        >
          {(data) =>
            data === null ? null : (
            <Table caption="보유 농산물별 추천 판매처">
              <THead>
                <TR>
                  <TH>보유 농산물</TH>
                  <TH>주요 상태</TH>
                  <TH>추천 판매처</TH>
                  <TH align="right">연계 물량</TH>
                </TR>
              </THead>
              <TBody>
                {data.lots.map(({ lot, allocated_kg, unallocated_kg, recommendations }) => {
                  const top = recommendations[0];
                  return (
                    <TR key={lot.id} data-testid="buyer-link-row">
                      <TD>
                        <span
                          className={cn('font-medium', lot.near_expiry && 'text-bad')}
                        >
                          {lot.grade_label} {formatKg(lot.qty_kg)}
                        </span>
                        <span className="block text-xs text-ink-muted">
                          {lot.crop_name}
                          {lot.expiry_date
                            ? ` · 판매기한 ${formatDate(lot.expiry_date)}`
                            : null}
                        </span>
                      </TD>
                      <TD>
                        {lot.near_expiry ? (
                          <Badge tone="bad" dot>
                            판매기한 임박 {lot.days_remaining}일
                          </Badge>
                        ) : (
                          <Badge tone="neutral">
                            잔여 {lot.days_remaining ?? '-'}일
                          </Badge>
                        )}
                      </TD>
                      <TD>
                        {top ? (
                          <>
                            <span className="font-medium">{top.buyer_name}</span>
                            <span className="block text-xs text-ink-muted">
                              {top.buyer_type_label} · {formatKm(top.distance_km)} ·{' '}
                              {top.reason}
                            </span>
                          </>
                        ) : (
                          <span className="text-ink-muted">연결 가능한 판매처가 없습니다</span>
                        )}
                      </TD>
                      <TD align="right">
                        {formatKg(allocated_kg)}
                        {unallocated_kg > 0 ? (
                          <span className="block text-xs text-warn">
                            미배정 {formatKg(unallocated_kg)}
                          </span>
                        ) : null}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
            )
          }
        </PanelState>
      </CardBody>
      {matches.status === 'success' && matches.data ? (
        <CardFooter>
          {matches.data.crop_name} 재고 {formatKg(matches.data.total_qty_kg)} 중{' '}
          {formatKg(matches.data.total_allocated_kg)} 연계 완료 · 미배정{' '}
          {formatKg(matches.data.total_unallocated_kg)}
        </CardFooter>
      ) : null}
    </Card>
  );
}
