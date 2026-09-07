/**
 * 단일 타입 API 클라이언트. 모든 화면이 이 모듈을 거친다 —
 * 컴포넌트에서 직접 `fetch` 하지 않는다 (docs/ARCHITECTURE.md §4).
 *
 * 내보내진 정적 사이트를 `/api` 를 답하는 FastAPI 가 같이 서빙하므로
 * 기본 base URL 은 상대경로다. 프론트만 따로 띄울 때는
 * `NEXT_PUBLIC_API_BASE_URL` 로 백엔드를 가리킨다.
 *
 * ## 기능 bead 가 이 파일을 확장하는 방법
 *
 * 아래 "기능별 엔드포인트" 아래에 **자기 SPEC 절 섹션만** 추가한다.
 * 공통 영역(요청 헬퍼, 오류 타입, 비동기 상태)은 건드리지 않는다.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? '';

/* -------------------------------------------------------------------------
   오류 · 비동기 상태 (공통 계약)
   ------------------------------------------------------------------------- */

/** API 가 non-2xx 를 돌려줬을 때. 네트워크 장애는 `NetworkError` 로 온다. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** FastAPI 의 `{"detail": ...}` 본문 (파싱된 경우) */
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** 서버에 닿지 못했을 때 (오프라인, DNS, CORS, 취소) */
export class NetworkError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
    this.name = 'NetworkError';
  }
}

/** 화면에 그대로 띄울 수 있는 한국어 메시지 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return '요청한 정보를 찾을 수 없습니다.';
    if (error.status === 422) return '요청 값이 올바르지 않습니다.';
    if (error.status >= 500) return '서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
    return error.message;
  }
  if (error instanceof NetworkError) return '서버에 연결하지 못했습니다. 네트워크를 확인해 주세요.';
  if (error instanceof Error) return error.message;
  return '알 수 없는 오류가 발생했습니다.';
}

/**
 * 데이터 로딩의 3-상태. 모든 화면이 같은 모양을 쓰므로 Skeleton /
 * AlertBanner / EmptyState 를 고르는 분기가 화면마다 달라지지 않는다.
 */
export type AsyncState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: null; error: unknown };

export const loadingState = <T,>(): AsyncState<T> => ({
  status: 'loading',
  data: null,
  error: null,
});
export const successState = <T,>(data: T): AsyncState<T> => ({
  status: 'success',
  data,
  error: null,
});
export const errorState = <T,>(error: unknown): AsyncState<T> => ({
  status: 'error',
  data: null,
  error,
});

/* -------------------------------------------------------------------------
   요청 헬퍼
   ------------------------------------------------------------------------- */

export interface RequestOptions {
  signal?: AbortSignal;
  /** 쿼리 문자열. `undefined` 값은 빠진다. */
  query?: Record<string, string | number | boolean | undefined>;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return `${BASE_URL}/api${path}${qs ? `?${qs}` : ''}`;
}

export async function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = buildUrl(path, options.query);
  return requestUrl<T>('GET', path, url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  });
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const url = buildUrl(path, options.query);
  return requestUrl<T>('POST', path, url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  });
}

async function requestUrl<T>(
  method: string,
  path: string,
  url: string,
  init: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    throw new NetworkError(`${method} /api${path} 요청이 실패했습니다.`, cause);
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, `${method} /api${path} 실패 (${response.status})`, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* -------------------------------------------------------------------------
   기능별 엔드포인트

   각 기능 bead 는 자기 SPEC 절 섹션을 아래에 추가한다.
   ------------------------------------------------------------------------- */

/* --- 기반 (SPEC 6) --- */

export interface Region {
  id: number;
  name: string;
  lat: number;
  lon: number;
}

export interface Crop {
  id: number;
  name: string;
  unit: string;
}

export const getHealth = (options?: RequestOptions) =>
  apiGet<{ status: string }>('/health', options);
export const getRegions = (options?: RequestOptions) => apiGet<Region[]>('/regions', options);
export const getCrops = (options?: RequestOptions) => apiGet<Crop[]>('/crops', options);
