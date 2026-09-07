'use client';

import { Badge, Button, Table, TBody, TD, TH, THead, TR } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatNumber, formatPercent } from '@/lib/format';
import { CONDITION_STATUS } from '@/lib/land';
import { FARM_STATUS_LABELS } from '@/components/ui';
import type { ParcelMatch } from '@/lib/api';

/**
 * 조건 비교 (SPEC 5.6 비교표).
 *
 * SPEC 의 표 그대로 **행이 평가 항목, 열이 농지**다. 점수·가중치는 서버가
 * `POST /api/parcels/match` 응답에 실어 주므로 화면은 재계산하지 않는다 —
 * 순위 근거가 화면과 API 에서 갈라지지 않게 하려는 것이다.
 */
export function ParcelCompare({
  results,
  weights,
  cropName,
  selectedId,
  onSelect,
  onApply,
  className,
}: {
  results: readonly ParcelMatch[];
  weights: Record<string, number>;
  cropName: string;
  selectedId?: number | null;
  onSelect?: (parcelId: number) => void;
  onApply?: (parcel: ParcelMatch) => void;
  className?: string;
}) {
  // 축 순서는 첫 결과의 순서를 따른다 — 서버의 WEIGHTS 정의 순서다.
  const axes = results[0]?.axes ?? [];

  return (
    <div className={cn('space-y-4', className)}>
      <Table caption={`${cropName} 재배 조건에 대한 유휴농지 적합도 비교표`} className="min-w-[36rem]">
        <THead>
          <TR>
            <TH className="w-40">평가 항목</TH>
            {results.map((result) => (
              <TH key={result.parcel_id} align="left">
                <button
                  type="button"
                  data-testid={`compare-head-${result.parcel_id}`}
                  onClick={() => onSelect?.(result.parcel_id)}
                  className={cn(
                    'rounded px-1 text-sm font-semibold transition-colors hover:text-accent',
                    selectedId === result.parcel_id && 'text-accent underline',
                  )}
                >
                  {result.name}
                </button>
                <span className="mt-0.5 block text-[11px] font-normal text-ink-muted">
                  {result.region_name}
                </span>
              </TH>
            ))}
          </TR>
        </THead>
        <TBody>
          {axes.map((axis, index) => (
            <TR key={axis.axis}>
              <TH scope="row" className="text-left font-medium">
                {axis.label}
                <span className="ml-1 text-[11px] font-normal text-ink-muted">
                  가중치 {formatPercent(weights[axis.axis] * 100, { digits: 0 })}
                </span>
              </TH>
              {results.map((result) => {
                const cell = result.axes[index];
                return (
                  <TD key={result.parcel_id}>
                    <span>{cell.value}</span>
                    <span className="mt-1 flex items-center gap-2">
                      <span
                        aria-hidden
                        className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-muted"
                      >
                        <span
                          className="block h-full rounded-full bg-accent"
                          style={{ width: `${Math.round(cell.score * 100)}%` }}
                        />
                      </span>
                      <span className="numeric text-[11px] text-ink-muted">
                        {formatNumber(cell.score, 2)}
                      </span>
                    </span>
                  </TD>
                );
              })}
            </TR>
          ))}

          <TR className="bg-surface-muted/50">
            <TH scope="row" className="text-left font-medium">
              적합도 점수
            </TH>
            {results.map((result) => (
              <TD key={result.parcel_id} className="numeric font-semibold">
                {formatPercent(result.total_score * 100, { digits: 1 })}
              </TD>
            ))}
          </TR>

          <TR>
            <TH scope="row" className="text-left font-medium">
              추천 결과
            </TH>
            {results.map((result) => (
              <TD key={result.parcel_id} data-testid={`compare-rank-${result.parcel_id}`}>
                <Badge tone={result.rank === 1 ? 'good' : 'neutral'}>{result.rank}위</Badge>
              </TD>
            ))}
          </TR>

          <TR>
            <TH scope="row" className="text-left font-medium">
              농지 상태
            </TH>
            {results.map((result) => (
              <TD key={result.parcel_id}>
                {FARM_STATUS_LABELS[CONDITION_STATUS[result.condition]]}
              </TD>
            ))}
          </TR>

          <TR>
            <TH scope="row" className="text-left font-medium">
              임대 신청
            </TH>
            {results.map((result) => (
              <TD key={result.parcel_id}>
                {result.status === 'idle' ? (
                  <Button
                    size="sm"
                    data-testid={`apply-${result.parcel_id}`}
                    onClick={() => onApply?.(result)}
                  >
                    임대 신청
                  </Button>
                ) : (
                  <span className="text-xs text-ink-muted">
                    {result.status === 'operating' ? '운영 중' : '전환 완료'}
                  </span>
                )}
              </TD>
            ))}
          </TR>
        </TBody>
      </Table>

      <ol className="space-y-2 text-sm" data-testid="compare-reasons">
        {results.map((result) => (
          <li key={result.parcel_id} className="flex gap-2 leading-relaxed">
            <Badge tone={result.rank === 1 ? 'good' : 'neutral'} className="mt-0.5 shrink-0">
              {result.rank}위
            </Badge>
            <span>
              <strong className="font-semibold">{result.name}</strong> — {result.reason}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
