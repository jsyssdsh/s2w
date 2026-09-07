/**
 * 차트 공통 설정. **차트 라이브러리는 recharts 하나뿐이다** —
 * 기능 bead 는 두 번째 차트 의존성을 추가하지 말고 이 래퍼를 쓴다.
 *
 * 색은 CSS 변수라 다크 모드에서 자동으로 바뀐다 (app/globals.css 참고).
 * 계열색은 5개까지만 쓴다 — 그 이상은 색으로 구분되지 않는다.
 */
export const SERIES_COLORS = [
  'var(--color-series-1)',
  'var(--color-series-2)',
  'var(--color-series-3)',
  'var(--color-series-4)',
  'var(--color-series-5)',
] as const;

export function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

export const AXIS_COLOR = 'var(--color-ink-muted)';
export const GRID_COLOR = 'var(--color-line)';
export const SURFACE_COLOR = 'var(--color-surface)';

export const AXIS_TICK = { fill: AXIS_COLOR, fontSize: 12 } as const;

export const TOOLTIP_STYLE = {
  contentStyle: {
    background: SURFACE_COLOR,
    border: '1px solid var(--color-line)',
    borderRadius: '0.5rem',
    fontSize: '0.8125rem',
    color: 'var(--color-ink)',
  },
  labelStyle: { color: 'var(--color-ink-muted)', marginBottom: '0.25rem' },
  itemStyle: { color: 'var(--color-ink)' },
} as const;

/** 한 계열의 정의 — 데이터 키와 한국어 라벨이 항상 함께 간다. */
export interface Series {
  dataKey: string;
  /** 범례·툴팁에 나오는 한국어 이름 */
  label: string;
  /** 기본은 계열 순서대로. 의미가 정해진 색(예: 초과공급=적)만 직접 지정한다. */
  color?: string;
}

export type ChartDatum = Record<string, string | number | null | undefined>;

/** 값 포맷터 — `lib/format.ts` 함수를 그대로 넘긴다. */
export type ValueFormatter = (value: number) => string;
export type TickFormatter = (value: string | number) => string;
