'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  createDealRequest,
  errorMessage,
  getFarmRecommendations,
  type Crop,
  type FarmRecommendation,
  type FarmRecommendationResponse,
} from '@/lib/api';
import { useApi } from '@/lib/useApi';
import {
  formatKg,
  formatKm,
  formatMoney,
  formatMonthDay,
  formatPercent,
  formatWon,
  formatWonPerKg,
} from '@/lib/format';
import { cn } from '@/lib/cn';
import {
  AlertBanner,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Select,
  StatTile,
  StatTileGrid,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from '@/components/ui';
import { PanelState } from './PanelState';

/**
 * SPEC 4.3 요약 타일 + AI 추천 농가 리스트.
 *
 * 리스트의 열은 SPEC 4.3 "향후 수정 계획" 이 요구하는 것 그대로다 —
 * 농가별 거리 · 공급량 · 품질 등급 · 운송비 · 예상 순수익 · 추천 이유에
 * 권장 거래가를 더했다. 숫자는 전부 `/api/distributor/farm-recommendations`
 * 에서 오고, 화면은 정렬과 표기만 한다.
 */

type SortKey =
  | 'farm_name'
  | 'ship_date'
  | 'qty_kg'
  | 'distance_km'
  | 'transport_cost_krw'
  | 'recommended_price_per_kg'
  | 'expected_net_profit_krw';

interface Column {
  key: SortKey | 'grade' | 'reason' | 'action';
  label: string;
  align?: 'left' | 'right';
  sortKey?: SortKey;
  /** 좁은 화면에서 숨긴다 — 표가 옆으로 끝없이 늘어나지 않게 */
  hideOnMobile?: boolean;
}

const COLUMNS: readonly Column[] = [
  { key: 'farm_name', label: '농가', sortKey: 'farm_name' },
  { key: 'ship_date', label: '출하일', sortKey: 'ship_date' },
  { key: 'grade', label: '품질 등급' },
  { key: 'qty_kg', label: '공급량', align: 'right', sortKey: 'qty_kg' },
  { key: 'distance_km', label: '거리', align: 'right', sortKey: 'distance_km' },
  {
    key: 'transport_cost_krw',
    label: '운송비',
    align: 'right',
    sortKey: 'transport_cost_krw',
    hideOnMobile: true,
  },
  {
    key: 'recommended_price_per_kg',
    label: '권장 거래가',
    align: 'right',
    sortKey: 'recommended_price_per_kg',
  },
  {
    key: 'expected_net_profit_krw',
    label: '예상 순수익',
    align: 'right',
    sortKey: 'expected_net_profit_krw',
  },
  { key: 'reason', label: '추천 이유', hideOnMobile: true },
  { key: 'action', label: '거래 요청', align: 'right' },
] as const;

type Direction = 'asc' | 'desc';

/** 기본 정렬 — 추천 대상이 먼저, 그 안에서 예상 순수익이 큰 순 (서버와 같은 순서). */
const DEFAULT_SORT: { key: SortKey; dir: Direction } = {
  key: 'expected_net_profit_krw',
  dir: 'desc',
};

function compare(a: FarmRecommendation, b: FarmRecommendation, key: SortKey): number {
  const left = a[key];
  const right = b[key];
  if (typeof left === 'number' && typeof right === 'number') return left - right;
  return String(left).localeCompare(String(right), 'ko');
}

function sortRows(
  rows: readonly FarmRecommendation[],
  key: SortKey,
  dir: Direction,
): FarmRecommendation[] {
  const factor = dir === 'asc' ? 1 : -1;
  return [...rows].sort(
    (a, b) =>
      Number(b.recommended) - Number(a.recommended) || factor * compare(a, b, key),
  );
}

export function FarmRecommendationPanel({
  wholesalerId,
  crops,
}: {
  wholesalerId: number;
  crops: readonly Crop[];
}) {
  const [cropId, setCropId] = useState<number | null>(null);
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [pending, setPending] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ tone: 'good' | 'bad'; text: string } | null>(null);
  const [sent, setSent] = useState<ReadonlySet<number>>(new Set());
  const [refreshToken, setRefreshToken] = useState(0);

  const state = useApi<FarmRecommendationResponse>(
    useCallback(
      (options) => {
        // 거래 요청을 보낸 뒤 목록을 다시 읽기 위한 의존성. `reload()` 와 달리
        // 화면을 비우지 않고 직전 데이터를 보여준 채 갱신한다.
        void refreshToken;
        return getFarmRecommendations(
          { wholesaler_id: wholesalerId, crop_id: cropId ?? undefined },
          options,
        );
      },
      [wholesalerId, cropId, refreshToken],
    ),
  );

  const requestDeal = useCallback(
    async (row: FarmRecommendation) => {
      setPending(row.shipment_id);
      setNotice(null);
      try {
        const result = await createDealRequest({
          wholesaler_id: wholesalerId,
          shipment_id: row.shipment_id,
          unit_price_krw: row.recommended_price_per_kg,
        });
        setSent((previous) => new Set(previous).add(row.shipment_id));
        setNotice({ tone: 'good', text: result.message });
        setRefreshToken((token) => token + 1);
      } catch (error) {
        setNotice({ tone: 'bad', text: errorMessage(error) });
      } finally {
        setPending(null);
      }
    },
    [wholesalerId],
  );

  const cropOptions = useMemo(
    () => [
      { value: '', label: '전체 품목' },
      ...crops.map((crop) => ({ value: String(crop.id), label: crop.name })),
    ],
    [crops],
  );

  const toggleSort = (key: SortKey) =>
    setSort((current) =>
      current.key === key
        ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'farm_name' || key === 'ship_date' ? 'asc' : 'desc' },
    );

  return (
    <section className="space-y-4" data-testid="farm-recommendations">
      {notice ? (
        <div data-testid="deal-request-notice">
          <AlertBanner tone={notice.tone}>{notice.text}</AlertBanner>
        </div>
      ) : null}
      <PanelState state={state} rows={5} cols={6}>
        {(data) => {
          const rows = sortRows(data.rows, sort.key, sort.dir);
          return (
            <>
              <StatTileGrid className="lg:grid-cols-3">
                <StatTile
                  label="공급 가능 건수"
                  value={String(data.summary.supply_count)}
                  unit="건"
                  hint={`${formatMonthDay(data.as_of)} ~ ${formatMonthDay(data.window_end)} 출하 · 총 ${formatKg(data.summary.supply_qty_kg)}`}
                  icon="📦"
                />
                <StatTile
                  label="AI 추천 건수"
                  value={String(data.summary.recommended_count)}
                  unit="건"
                  hint={`매입 가능 ${formatKg(data.summary.purchasable_qty_kg)} · 요청 보낸 건 ${data.summary.requested_count}건`}
                  icon="🤖"
                />
                <StatTile
                  label="예상 금액"
                  value={formatMoney(data.summary.expected_amount_krw)}
                  hint={`예상 순수익 ${formatMoney(data.summary.expected_net_profit_krw)}`}
                  icon="💰"
                />
              </StatTileGrid>

              <Card>
                <CardHeader
                  title="AI 추천 농가 리스트"
                  description="권장 거래가는 예상 판매금액에서 수수료·운송비·목표 마진을 뺀 값입니다. 열 제목을 눌러 정렬할 수 있습니다."
                  action={
                    <Select
                      label="품목"
                      options={cropOptions}
                      value={cropId === null ? '' : String(cropId)}
                      data-testid="recommendation-crop-filter"
                      onChange={(event) =>
                        setCropId(event.target.value ? Number(event.target.value) : null)
                      }
                    />
                  }
                />
                <CardBody className="px-0 py-0">
                  <Table caption="AI 추천 농가 리스트">
                    <THead>
                      <TR>
                        {COLUMNS.map((column) => {
                          const sortKey = column.sortKey;
                          return (
                            <TH
                              key={column.key}
                              align={column.align}
                              className={cn(column.hideOnMobile && 'hidden lg:table-cell')}
                              aria-sort={
                                sortKey === undefined
                                  ? undefined
                                  : sort.key === sortKey
                                    ? sort.dir === 'asc'
                                      ? 'ascending'
                                      : 'descending'
                                    : 'none'
                              }
                            >
                              {sortKey ? (
                                <button
                                  type="button"
                                  className="inline-flex items-center gap-1 hover:text-ink"
                                  data-testid={`sort-${sortKey}`}
                                  onClick={() => toggleSort(sortKey)}
                                >
                                  {column.label}
                                  <span aria-hidden className="text-[0.6rem]">
                                    {sort.key === sortKey
                                      ? sort.dir === 'asc'
                                        ? '▲'
                                        : '▼'
                                      : '↕'}
                                  </span>
                                </button>
                              ) : (
                                column.label
                              )}
                            </TH>
                          );
                        })}
                      </TR>
                    </THead>
                    <TBody>
                      {rows.map((row) => {
                        const requested = row.requested || sent.has(row.shipment_id);
                        return (
                          <TR
                            key={row.shipment_id}
                            data-testid="recommendation-row"
                            data-shipment={row.shipment_id}
                            className={cn(!row.recommended && 'opacity-70')}
                          >
                            <TD>
                              <span className="font-medium">{row.farm_name}</span>
                              <span className="block text-xs text-ink-muted">
                                {row.region_name} · {row.crop_name}
                              </span>
                            </TD>
                            <TD>{formatMonthDay(row.ship_date)}</TD>
                            <TD>
                              <Badge tone={row.recommended ? 'good' : 'neutral'}>
                                {row.grade_label}
                              </Badge>
                            </TD>
                            <TD align="right">
                              {formatKg(row.qty_kg)}
                              {row.unsold_kg > 0 ? (
                                <span className="block text-xs text-ink-muted">
                                  매입 {formatKg(row.purchasable_kg)}
                                </span>
                              ) : null}
                            </TD>
                            <TD align="right">{formatKm(row.distance_km)}</TD>
                            <TD align="right" className="hidden lg:table-cell">
                              {formatWon(row.transport_cost_krw)}
                            </TD>
                            <TD align="right">
                              {formatWonPerKg(row.recommended_price_per_kg)}
                              <span className="block text-xs text-ink-muted">
                                예상 판매가의 {formatPercent(row.offer_pct)}
                              </span>
                            </TD>
                            <TD align="right">
                              <span
                                className={cn(
                                  'font-medium',
                                  row.expected_net_profit_krw >= 0 ? 'text-good' : 'text-bad',
                                )}
                              >
                                {formatMoney(row.expected_net_profit_krw)}
                              </span>
                            </TD>
                            <TD className="hidden max-w-xs lg:table-cell">
                              <span className="text-xs leading-relaxed text-ink-muted">
                                {row.reason}
                              </span>
                            </TD>
                            <TD align="right">
                              <Button
                                size="sm"
                                variant={row.recommended ? 'primary' : 'secondary'}
                                data-testid="deal-request-button"
                                disabled={
                                  requested ||
                                  pending === row.shipment_id ||
                                  row.purchasable_kg <= 0
                                }
                                onClick={() => void requestDeal(row)}
                              >
                                {requested
                                  ? '요청 완료'
                                  : pending === row.shipment_id
                                    ? '보내는 중…'
                                    : '거래 요청 보내기'}
                              </Button>
                            </TD>
                          </TR>
                        );
                      })}
                    </TBody>
                  </Table>
                  {rows.length === 0 ? (
                    <p className="px-5 py-8 text-center text-sm text-ink-muted">
                      선택한 조건에 매입 가능한 출하가 없습니다.
                    </p>
                  ) : null}
                </CardBody>
              </Card>
            </>
          );
        }}
      </PanelState>
    </section>
  );
}
