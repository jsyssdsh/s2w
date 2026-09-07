/**
 * 표시 형식 유틸 (SPEC 4·5 의 표 표기를 그대로 재현한다).
 *
 * docs/ARCHITECTURE.md §5 대로 **반올림과 단위 표기는 표현 계층에서만** 한다.
 * 화면 코드는 여기 있는 함수만 쓰고, 자체 포맷 코드를 만들지 않는다.
 *
 * 모든 함수는 순수 함수이고 로케일 데이터에 의존하지 않는다 —
 * 정적 빌드(Node)와 브라우저가 같은 문자열을 내야 하기 때문이다.
 */

/** 자리수 구분 — "1234567" → "1,234,567" */
function groupDigits(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function splitNumber(value: number, digits: number): { sign: string; body: string } {
  const rounded = round(value, digits);
  const sign = rounded < 0 ? '-' : '';
  const fixed = Math.abs(rounded).toFixed(digits);
  const [int, frac] = fixed.split('.');
  return { sign, body: groupDigits(int) + (frac ? `.${frac}` : '') };
}

/** 표시용 반올림. 0.5 는 항상 절댓값이 커지는 쪽으로. */
export function round(value: number, digits = 0): number {
  const factor = 10 ** digits;
  return (Math.sign(value) * Math.round(Math.abs(value) * factor)) / factor;
}

/** 1234567 → "1,234,567" */
export function formatNumber(value: number, digits = 0): string {
  const { sign, body } = splitNumber(value, digits);
  return sign + body;
}

/* -------------------------------------------------------------------------
   금액 (KRW)
   ------------------------------------------------------------------------- */

/** 2450 → "2,450원" */
export function formatWon(value: number): string {
  return `${formatNumber(value)}원`;
}

/** 2450 → "2,450원/kg" (SPEC 5.1·5.2 의 단가 표기) */
export function formatWonPerKg(value: number): string {
  return `${formatNumber(value)}원/kg`;
}

/**
 * 만 원 단위 표기 — SPEC 5.2 의 "239만 5,000원", "245만 원", "18만 원".
 *
 * 1만 원 미만이면 원으로 쓰고, 만 단위로 딱 떨어지면 뒷자리를 생략한다.
 */
export function formatManWon(value: number): string {
  const won = Math.round(value);
  const sign = won < 0 ? '-' : '';
  const abs = Math.abs(won);
  if (abs < 10_000) return `${sign}${formatNumber(abs)}원`;

  const man = Math.floor(abs / 10_000);
  const rest = abs % 10_000;
  if (rest === 0) return `${sign}${formatNumber(man)}만 원`;
  return `${sign}${formatNumber(man)}만 ${formatNumber(rest)}원`;
}

/**
 * 표의 금액 열 기본값 — 1만 원 이상이면 만 원 단위, 그 미만은 원 단위.
 */
export function formatMoney(value: number): string {
  return Math.abs(value) >= 10_000 ? formatManWon(value) : formatWon(value);
}

/* -------------------------------------------------------------------------
   수량 · 물리 단위
   ------------------------------------------------------------------------- */

/** 1000 → "1,000kg" */
export function formatKg(kg: number, digits = 0): string {
  return `${formatNumber(kg, digits)}kg`;
}

/** kg 를 톤으로 — 120000 → "120톤" (SPEC 5.4 의 수급 집계 표기) */
export function formatTon(kg: number, digits = 0): string {
  return `${formatNumber(kg / 1000, digits)}톤`;
}

/**
 * SPEC 이 톤을 쓰는 자리(수급 집계)와 kg 를 쓰는 자리(출하량)를 구분해야 하므로
 * 단위를 명시적으로 받는다. 자동 전환은 하지 않는다.
 */
export function formatWeight(kg: number, unit: 'kg' | 'ton' = 'kg', digits = 0): string {
  return unit === 'ton' ? formatTon(kg, digits) : formatKg(kg, digits);
}

/** 면적 — 900 → "900평" */
export function formatPyeong(pyeong: number): string {
  return `${formatNumber(pyeong)}평`;
}

/** 거리 — 23.7 → "24km" */
export function formatKm(km: number, digits = 0): string {
  return `${formatNumber(km, digits)}km`;
}

/** 온도 — 29.4 → "29.4℃" */
export function formatCelsius(value: number, digits = 1): string {
  return `${formatNumber(value, digits)}℃`;
}

/* -------------------------------------------------------------------------
   비율
   ------------------------------------------------------------------------- */

export interface PercentOptions {
  /** 0 이 아닐 때 부호를 항상 붙인다 — 증감 표기용 ("+5.3%") */
  signed?: boolean;
  digits?: number;
}

/** 이미 백분율인 값 (예: `humidity_pct` 68) → "68%" */
export function formatPercent(pct: number, options: PercentOptions = {}): string {
  const { signed = false, digits = Number.isInteger(pct) ? 0 : 1 } = options;
  const rounded = round(pct, digits);
  const { sign, body } = splitNumber(rounded, digits);
  const prefix = sign || (signed && rounded > 0 ? '+' : '');
  return `${prefix}${body}%`;
}

/** 0.0–1.0 비율 (예: `fee_rate` 0.03) → "3%" */
export function formatRatio(ratio: number, options: PercentOptions = {}): string {
  return formatPercent(ratio * 100, options);
}

export type Trend = 'up' | 'down' | 'flat';

/** 증감 방향 — 0 은 'flat' */
export function trendOf(delta: number): Trend {
  if (delta > 0) return 'up';
  if (delta < 0) return 'down';
  return 'flat';
}

/**
 * SPEC 5.1 의 "5.3% 상승" 표기. `pct` 는 이미 백분율인 변동률(+5.3 / −5.3).
 */
export function formatTrend(pct: number, digits = 1): string {
  const trend = trendOf(round(pct, digits));
  if (trend === 'flat') return '변동 없음';
  return `${formatPercent(Math.abs(pct), { digits })} ${trend === 'up' ? '상승' : '하락'}`;
}

/* -------------------------------------------------------------------------
   날짜
   ------------------------------------------------------------------------- */

export type DateInput = string | number | Date;

/**
 * 날짜를 연·월·일로 쪼갠다.
 *
 * `YYYY-MM-DD` 문자열은 **문자열 그대로** 읽는다. `new Date('2026-08-08')` 은
 * UTC 자정으로 해석돼 시간대에 따라 하루가 밀리기 때문이다.
 */
function parts(input: DateInput): { y: number; m: number; d: number } {
  if (typeof input === 'string') {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(input);
    if (match) {
      return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
    }
  }
  const date = input instanceof Date ? input : new Date(input);
  return { y: date.getFullYear(), m: date.getMonth() + 1, d: date.getDate() };
}

/** "2026-08-08" → "2026년 8월 8일" */
export function formatDate(input: DateInput): string {
  const { y, m, d } = parts(input);
  return `${y}년 ${m}월 ${d}일`;
}

/** "2026-08-08" → "8월 8일" (SPEC 5.1 의 출하일 표기) */
export function formatMonthDay(input: DateInput): string {
  const { m, d } = parts(input);
  return `${m}월 ${d}일`;
}

/** 차트 축 라벨 — "8/8" */
export function formatAxisDate(input: DateInput): string {
  const { m, d } = parts(input);
  return `${m}/${d}`;
}

/** ISO 날짜 문자열 — 날짜를 API 로 되돌려 보낼 때 */
export function toIsoDate(input: DateInput): string {
  const { y, m, d } = parts(input);
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

/** n 일 뒤(음수면 앞)의 `YYYY-MM-DD`. 시간대·벽시계에 의존하지 않는다. */
export function addDays(input: DateInput, days: number): string {
  const { y, m, d } = parts(input);
  const shifted = new Date(Date.UTC(y, m - 1, d + days));
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
}

/** 두 날짜 사이의 일수 (부호 있음) */
export function daysBetween(from: DateInput, to: DateInput): number {
  const a = parts(from);
  const b = parts(to);
  return Math.round(
    (Date.UTC(b.y, b.m - 1, b.d) - Date.UTC(a.y, a.m - 1, a.d)) / 86_400_000,
  );
}
