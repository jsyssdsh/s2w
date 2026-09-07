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

/* --- 농가 대시보드 · 출하 (SPEC 4.2 / 7.1) --- */

export type Grade = 'special' | 'standard' | 'offgrade' | 'near_expiry';

export const GRADE_OPTIONS: readonly { value: Grade; label: string }[] = [
  { value: 'special', label: '특상품' },
  { value: 'standard', label: '상품' },
  { value: 'offgrade', label: '규격 외' },
  { value: 'near_expiry', label: '판매기한 임박' },
];

export type DealStatus = 'proposed' | 'accepted' | 'rejected' | 'settled';

export interface CropStatus {
  smartfarm_id: number;
  smartfarm_name: string;
  smartfarm_type: string;
  crop_id: number;
  crop_name: string;
  started_on: string;
  expected_yield_kg: number;
}

export interface Farm {
  farm_id: number;
  name: string;
  owner_name: string;
  region_id: number;
  region_name: string;
  parcel_id: number | null;
  crops: CropStatus[];
  total_expected_yield_kg: number;
}

export interface DealLine {
  deal_id: number;
  wholesaler_id: number;
  wholesaler_name: string;
  agreed_price_krw: number;
  status: DealStatus;
  status_label: string;
  decided_on: string | null;
}

export interface Shipment {
  shipment_id: number;
  farm_id: number;
  crop_id: number;
  crop_name: string;
  qty_kg: number;
  ship_date: string;
  grade: Grade;
  grade_label: string;
  deals: DealLine[];
}

export interface ShipmentInput {
  crop_id: number;
  qty_kg: number;
  ship_date: string;
  grade: Grade;
}

export interface Wholesaler {
  id: number;
  name: string;
  region_id: number;
  lat: number;
  lon: number;
  unit_price_krw: number;
  capacity_kg: number;
  fee_rate: number;
  transport_cost_per_km: number;
}

export const getFarms = (options?: RequestOptions) => apiGet<Farm[]>('/farms', options);

export const getWholesalers = (options?: RequestOptions) =>
  apiGet<Wholesaler[]>('/wholesalers', options);

export const getShipments = (farmId: number, options?: RequestOptions) =>
  apiGet<Shipment[]>('/shipments', { ...options, query: { farm_id: farmId } });

export const createShipment = (
  farmId: number,
  body: ShipmentInput,
  options?: RequestOptions,
) => apiPost<Shipment>(`/farms/${farmId}/shipments`, body, options);

/* --- AI 농산물 시세 예측 (SPEC 5.1) --- */

export interface ShippingWindowRequest {
  crop_id: number;
  region_id: number;
  qty_kg: number;
  /** 첫 날짜가 비교 기준이 된다 */
  candidate_dates: string[];
  as_of?: string | null;
}

export interface ShippingWindowRow {
  date: string;
  horizon_days: number;
  expected_price_per_kg: number;
  expected_revenue_krw: number;
  change_pct_vs_baseline: number;
  lower_price_per_kg: number;
  upper_price_per_kg: number;
  expected_volume_kg: number;
  supply_outlook: string;
  guidance: string;
  is_baseline: boolean;
}

export interface ForecastModelInfo {
  mape_pct: number;
  backtest_days: number;
  trained_through: string;
  max_horizon_days: number;
}

export interface ShippingWindow {
  crop_id: number;
  crop_name: string;
  region_id: number;
  region_name: string;
  qty_kg: number;
  as_of: string;
  baseline_date: string;
  model: ForecastModelInfo;
  rows: ShippingWindowRow[];
}

export interface PriceActual {
  date: string;
  price_per_kg: number;
  volume_kg: number;
}

export interface PriceForecastPoint {
  date: string;
  horizon_days: number;
  expected_price_per_kg: number;
  lower_price_per_kg: number;
  upper_price_per_kg: number;
  expected_volume_kg: number;
  supply_outlook: string;
}

export interface PriceForecast {
  crop_id: number;
  crop_name: string;
  region_id: number;
  region_name: string;
  as_of: string;
  horizon_days: number;
  model: ForecastModelInfo;
  actuals: PriceActual[];
  forecast: PriceForecastPoint[];
}

export const getPriceForecast = (
  params: { crop_id: number; region_id: number; horizon?: number; as_of?: string },
  options: RequestOptions = {},
) => apiGet<PriceForecast>('/forecast/price', { ...options, query: { ...params } });

export const getShippingWindow = (body: ShippingWindowRequest, options?: RequestOptions) =>
  apiPost<ShippingWindow>('/forecast/shipping-window', body, options);

/* --- 농가 맞춤형 도매처 추천 · 거래 (SPEC 5.2 / 7.1) --- */

export interface WholesalerReliability {
  score: number;
  fulfilled: number;
  decided: number;
  proposed_total: number;
}

export interface WholesalerCandidate {
  rank: number;
  wholesaler_id: number;
  name: string;
  distance_km: number;
  unit_price_krw: number;
  list_unit_price_krw: number;
  capacity_kg: number;
  /** min(출하량, 구매 가능량) */
  sellable_kg: number;
  unsold_kg: number;
  gross_krw: number;
  transport_cost_krw: number;
  fee_rate: number;
  fee_krw: number;
  net_profit_krw: number;
  ranking_score_krw: number;
  reliability: WholesalerReliability;
  reason: string;
}

export interface WholesalerRecommendation {
  farm_id: number;
  farm_name: string;
  crop_id: number;
  crop_name: string;
  qty_kg: number;
  ship_date: string;
  price_source: 'static' | 'forecast';
  notes: string[];
  candidates: WholesalerCandidate[];
}

export interface Deal {
  id: number;
  shipment_id: number;
  wholesaler_id: number;
  agreed_price_krw: number;
  status: DealStatus;
  decided_on: string | null;
}

export const getWholesalerRecommendations = (
  body: {
    farm_id: number;
    crop_id: number;
    qty_kg: number;
    ship_date: string;
    use_forecast?: boolean;
  },
  options?: RequestOptions,
) => apiPost<WholesalerRecommendation>('/recommendations/wholesalers', body, options);

export const createDeal = (
  body: {
    shipment_id: number;
    wholesaler_id: number;
    status?: DealStatus;
    agreed_price_krw?: number;
    /** 함께 봤지만 고르지 않은 도매처 — SPEC 7.1 피드백 루프의 음의 신호 */
    alternatives?: number[];
  },
  options?: RequestOptions,
) => apiPost<Deal>('/deals', body, options);

export const getDeals = (options?: RequestOptions) => apiGet<Deal[]>('/deals', options);

/* --- 도매처 맞춤 판매처 연계 (SPEC 5.3) --- */

// 등급 문자열(`Grade`)은 SPEC 4.2 출하 등록과 같은 값이라 위에서 그대로 쓴다.

export interface InventoryLot {
  id: number;
  wholesaler_id: number;
  crop_id: number;
  crop_name: string;
  grade: Grade;
  grade_label: string;
  qty_kg: number;
  expiry_date: string | null;
  days_remaining: number | null;
  near_expiry: boolean;
}

export interface BuyerMatch {
  buyer_id: number;
  buyer_name: string;
  buyer_type: string;
  buyer_type_label: string;
  distance_km: number;
  demand_kg: number;
  matched_qty_kg: number;
  score: number;
  reason: string;
}

export interface LotRecommendation {
  lot: InventoryLot;
  allocated_kg: number;
  unallocated_kg: number;
  recommendations: BuyerMatch[];
}

export interface BuyerMatchResponse {
  wholesaler_id: number;
  wholesaler_name: string;
  crop_id: number;
  crop_name: string;
  as_of: string;
  total_qty_kg: number;
  total_allocated_kg: number;
  total_unallocated_kg: number;
  lots: LotRecommendation[];
}

export const getWholesalerInventory = (
  wholesalerId: number,
  params?: { crop_id?: number; as_of?: string },
  options?: RequestOptions,
) =>
  apiGet<InventoryLot[]>(`/wholesalers/${wholesalerId}/inventory`, {
    ...options,
    query: params,
  });

export const matchBuyers = (
  body: { wholesaler_id: number; crop_id: number; as_of?: string },
  options?: RequestOptions,
) => apiPost<BuyerMatchResponse>('/recommendations/buyers', body, options);

/* --- 지역별 수급 위험 조기 알림 (SPEC 5.4) --- */

/** 백엔드 `RiskTier` — 값이 그대로 화면에 나가는 한국어 라벨이다. */
export type RiskTier = '안정' | '주의' | '위험';

export interface AnalysisWindow {
  start: string;
  end: string;
}

export interface VolumeBreakdown {
  farm_shipment_kg: number;
  wholesaler_inventory_kg: number;
  total_supply_kg: number;
  buyer_demand_kg: number;
  excess_supply_kg: number;
}

export interface MitigationAction {
  channel: string;
  label: string;
  qty_kg: number;
  capacity_kg: number;
  headroom_kg: number;
  detail: string;
}

export interface MitigationPlan {
  actions: MitigationAction[];
  target_kg: number;
  planned_kg: number;
  shortfall_kg: number;
  is_fully_covered: boolean;
}

export interface SupplyRisk {
  region: Region;
  crop: Crop;
  window: AnalysisWindow;
  volumes: VolumeBreakdown;
  excess_ratio: number;
  risk_tier: RiskTier;
  mitigation: MitigationPlan;
}

export interface Alert {
  region: Region;
  crop: Crop;
  window: AnalysisWindow;
  risk_tier: RiskTier;
  excess_ratio: number;
  total_supply_kg: number;
  buyer_demand_kg: number;
  excess_supply_kg: number;
  shortfall_kg: number;
  headline: string;
}

export const getAlerts = (
  params: { region_id: number; as_of?: string; window_days?: number },
  options?: RequestOptions,
) => apiGet<Alert[]>('/alerts', { ...options, query: params });

export const getSupplyRisk = (
  params: { region_id: number; crop_id: number; window_start?: string; window_end?: string },
  options?: RequestOptions,
) => apiGet<SupplyRisk>('/supply-risk', { ...options, query: params });

/* --- 유통업체 대시보드 (SPEC 4.3) --- */

export interface DistributorWholesaler {
  id: number;
  name: string;
  region_id: number;
  region_name: string;
  unit_price_krw: number;
  capacity_kg: number;
  fee_rate: number;
  transport_cost_per_km: number;
  inventory_lot_count: number;
}

export interface FarmRecommendation {
  shipment_id: number;
  farm_id: number;
  farm_name: string;
  region_id: number;
  region_name: string;
  crop_id: number;
  crop_name: string;
  grade: Grade;
  grade_label: string;
  ship_date: string;
  qty_kg: number;
  purchasable_kg: number;
  unsold_kg: number;
  distance_km: number;
  transport_cost_krw: number;
  market_price_per_kg: number;
  graded_price_per_kg: number;
  recommended_price_per_kg: number;
  offer_pct: number;
  purchase_cost_krw: number;
  resale_revenue_krw: number;
  fee_krw: number;
  expected_net_profit_krw: number;
  margin_pct: number;
  /** market = 실측 도매 시세 · forecast = SPEC 5.1 예측 · list = 도매처 고시 단가 */
  price_source: 'market' | 'forecast' | 'list';
  requested: boolean;
  recommended: boolean;
  reason: string;
}

export interface RecommendationSummary {
  supply_count: number;
  recommended_count: number;
  expected_amount_krw: number;
  expected_net_profit_krw: number;
  supply_qty_kg: number;
  purchasable_qty_kg: number;
  requested_count: number;
}

export interface FarmRecommendationResponse {
  wholesaler: DistributorWholesaler;
  as_of: string;
  window_end: string;
  summary: RecommendationSummary;
  rows: FarmRecommendation[];
}

export interface DealRequest {
  id: number;
  shipment_id: number;
  wholesaler_id: number;
  wholesaler_name: string;
  farm_name: string;
  crop_name: string;
  qty_kg: number;
  unit_price_krw: number;
  agreed_price_krw: number;
  status: string;
  created: boolean;
  message: string;
}

export interface MarketPoint {
  date: string;
  price_per_kg: number;
  volume_kg: number;
}

export interface MarketRow {
  crop_id: number;
  crop_name: string;
  unit: string;
  price_per_kg: number;
  previous_price_per_kg: number;
  price_change_pct: number;
  volume_kg: number;
  previous_volume_kg: number;
  demand_change_pct: number;
  /** 상승세 · 하락세 · 보합 */
  trend: string;
  series: MarketPoint[];
}

export interface MarketSnapshot {
  region_id: number;
  region_name: string;
  as_of: string;
  lookback_days: number;
  rows: MarketRow[];
}

export const getDistributorWholesalers = (options?: RequestOptions) =>
  apiGet<DistributorWholesaler[]>('/distributor/wholesalers', options);

export const getFarmRecommendations = (
  params: {
    wholesaler_id: number;
    crop_id?: number;
    as_of?: string;
    window_days?: number;
    use_forecast?: boolean;
  },
  options?: RequestOptions,
) => apiGet<FarmRecommendationResponse>('/distributor/farm-recommendations', {
  ...options,
  query: params,
});

export const createDealRequest = (
  body: { wholesaler_id: number; shipment_id: number; unit_price_krw?: number; as_of?: string },
  options?: RequestOptions,
) => apiPost<DealRequest>('/distributor/deal-requests', body, options);

export const getMarketSnapshot = (
  params?: { region_id?: number; as_of?: string; lookback_days?: number },
  options?: RequestOptions,
) => apiGet<MarketSnapshot>('/distributor/market', { ...options, query: params });


/* --- 스마트팜 재배환경 통합관리 (SPEC 5.5 / 7.2) --- */

export type ControlDevice = 'pump' | 'fan' | 'light';

/** SPEC 4.5 센서 변화 그래프가 그릴 수 있는 측정 항목 */
export const SENSOR_METRICS = ['temp_c', 'humidity_pct', 'soil_moisture_pct', 'lux'] as const;
export type SensorMetric = (typeof SENSOR_METRICS)[number];

export interface MetricStatus {
  metric: string;
  label: string;
  unit: string;
  value: number;
  /** 서버가 정한 표시 문자열 — 조도는 절대값이 아니라 "기준의 82%" 다 */
  display: string;
  target_min: number | null;
  target_max: number | null;
  target_display: string;
  in_range: boolean;
  device: ControlDevice | null;
  device_action: string | null;
  control_display: string;
}

export interface DeviceState {
  device: ControlDevice;
  action: string;
  since: string | null;
  reason: string;
}

export interface SmartfarmStatus {
  smartfarm_id: number;
  name: string;
  farm_id: number;
  type: string;
  crop_id: number;
  crop: string;
  ts: string | null;
  metrics: MetricStatus[];
  devices: DeviceState[];
}

export interface SensorPoint {
  ts: string;
  temp_c?: number | null;
  humidity_pct?: number | null;
  soil_moisture_pct?: number | null;
  lux?: number | null;
}

export interface SensorSeries {
  smartfarm_id: number;
  metrics: string[];
  hours: number;
  from_ts: string | null;
  to_ts: string | null;
  points: SensorPoint[];
}

export interface ControlEvent {
  id: number;
  smartfarm_id: number;
  ts: string;
  device: ControlDevice;
  action: string;
  reason: string;
  metric: string | null;
  value_before: number | null;
  value_after: number | null;
}

export const getSmartfarmStatus = (smartfarmId: number, options?: RequestOptions) =>
  apiGet<SmartfarmStatus>(`/smartfarm/${smartfarmId}/status`, options);

export const getSensorSeries = (
  smartfarmId: number,
  params: { metric?: SensorMetric; hours?: number } = {},
  options: RequestOptions = {},
) =>
  apiGet<SensorSeries>(`/smartfarm/${smartfarmId}/readings`, {
    ...options,
    query: { metric: params.metric, hours: params.hours },
  });

export const getSmartfarmControls = (
  smartfarmId: number,
  limit: number,
  options?: RequestOptions,
) => apiGet<ControlEvent[]>(`/smartfarm/${smartfarmId}/controls`, { ...options, query: { limit } });

/* --- 유휴농지 탐색·지도·상세 (SPEC 5.6 / 7.3 / 4.4 / 4.5) --- */

export type ParcelStatus = 'idle' | 'operating' | 'converted';
export type ParcelCondition = 'best' | 'good' | 'needs_improvement';
export type ColdStorageAccess = 'possible' | 'limited' | 'none';
/** SPEC 4.4 지도 상태 색상 — 상태 최상(녹) / 상태 양호(황) / 개선 필요(적) */
export type ParcelColor = 'green' | 'amber' | 'red';

export interface ParcelProperties {
  id: number;
  name: string;
  region_id: number;
  region_name: string;
  area_pyeong: number;
  monthly_rent_krw: number;
  water_access: boolean;
  cold_storage_access: ColdStorageAccess;
  soil_grade: string;
  status: ParcelStatus;
  status_label: string;
  condition: ParcelCondition;
  condition_label: string;
  color: ParcelColor;
  color_hex: string;
}

export interface ParcelFeature {
  type: 'Feature';
  id: number;
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: ParcelProperties;
}

export interface ParcelFeatureCollection {
  type: 'FeatureCollection';
  features: ParcelFeature[];
}

export interface ParcelSummary {
  region_id: number | null;
  region_name: string | null;
  total_count: number;
  idle_count: number;
  operating_count: number;
  converted_count: number;
  applications_today: number;
  ai_recommended_deals: number;
  land_utilization_rate: number;
  as_of: string;
}

export interface AxisScore {
  axis: string;
  label: string;
  value: string;
  score: number;
  weight: number;
  weighted: number;
}

export interface ParcelMatch {
  rank: number;
  parcel_id: number;
  name: string;
  region_id: number;
  region_name: string;
  area_pyeong: number;
  monthly_rent_krw: number;
  water_access: boolean;
  cold_storage_access: ColdStorageAccess;
  soil_grade: string;
  status: ParcelStatus;
  condition: ParcelCondition;
  lat: number;
  lon: number;
  nearest_wholesaler: { id: number; name: string; distance_km: number } | null;
  total_score: number;
  axes: AxisScore[];
  reason: string;
}

export interface ParcelMatchRequest {
  crop_id: number;
  area_min_pyeong: number;
  area_max_pyeong: number;
  budget_krw_per_month: number;
  region_id?: number | null;
  limit?: number | null;
  as_of?: string | null;
}

export interface ParcelMatchResponse {
  crop_id: number;
  crop_name: string;
  as_of: string;
  weights: Record<string, number>;
  results: ParcelMatch[];
}

export interface ParcelFacility {
  kind: string;
  name: string;
  distance_km: number | null;
  note: string;
}

export interface ParcelSmartfarm {
  id: number;
  name: string;
  type: string;
  crop_id: number;
  crop_name: string;
  started_on: string;
  expected_yield_kg: number;
}

export interface ParcelDetail {
  id: number;
  name: string;
  region_id: number;
  region_name: string;
  area_pyeong: number;
  monthly_rent_krw: number;
  soil_grade: string;
  water_access: boolean;
  cold_storage_access: ColdStorageAccess;
  cold_storage_label: string;
  status: ParcelStatus;
  status_label: string;
  condition: ParcelCondition;
  condition_label: string;
  color: ParcelColor;
  color_hex: string;
  lat: number;
  lon: number;
  owner: { id: number; name: string; phone: string | null } | null;
  nearby_facilities: ParcelFacility[];
  smartfarms: ParcelSmartfarm[];
  land_utilization_rate: number;
  application_count: number;
}

export interface ParcelApplicationRequest {
  crop_id: number;
  applicant_name: string;
  applicant_id?: number | null;
  phone?: string | null;
  lease_months?: number;
  message?: string;
  match_score?: number | null;
  applied_on?: string | null;
}

export interface ParcelApplicationResponse {
  application: {
    id: number;
    parcel_id: number;
    crop_id: number;
    applicant_id: number | null;
    applicant_name: string;
    phone: string | null;
    lease_months: number;
    message: string;
    match_score: number | null;
    status: 'pending' | 'accepted' | 'rejected';
    applied_on: string;
  };
  parcel_status: ParcelStatus;
  parcel_status_label: string;
}

export interface ParcelRegisterRequest {
  name: string;
  region_id: number;
  area_pyeong: number;
  monthly_rent_krw: number;
  water_access?: boolean;
  cold_storage_access?: ColdStorageAccess;
  soil_grade?: string;
  lat?: number | null;
  lon?: number | null;
  condition?: ParcelCondition;
  owner_name?: string | null;
  owner_phone?: string | null;
}

/** SPEC 7.3 유휴농지 등록 — 응답은 지도가 바로 쓸 수 있는 GeoJSON 피처다. */
export const registerParcel = (body: ParcelRegisterRequest, options?: RequestOptions) =>
  apiPost<ParcelFeature>('/parcels', body, options);

export const getParcelGeoJson = (regionId?: number | null, options: RequestOptions = {}) =>
  apiGet<ParcelFeatureCollection>('/parcels/geojson', {
    ...options,
    query: { region_id: regionId ?? undefined },
  });

export const getParcelSummary = (regionId?: number | null, options: RequestOptions = {}) =>
  apiGet<ParcelSummary>('/parcels/summary', {
    ...options,
    query: { region_id: regionId ?? undefined },
  });

export const getParcelDetail = (parcelId: number, options?: RequestOptions) =>
  apiGet<ParcelDetail>(`/parcels/${parcelId}`, options);

export const matchParcels = (body: ParcelMatchRequest, options?: RequestOptions) =>
  apiPost<ParcelMatchResponse>('/parcels/match', body, options);

export const applyForParcel = (
  parcelId: number,
  body: ParcelApplicationRequest,
  options?: RequestOptions,
) => apiPost<ParcelApplicationResponse>(`/parcels/${parcelId}/applications`, body, options);
