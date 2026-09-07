'use client';

import { useId, useMemo } from 'react';
import { cn } from '@/lib/cn';
import { formatKm, formatNumber } from '@/lib/format';
import { COLOR_VARS, haversineKm } from '@/lib/land';
import type { ParcelColor } from '@/lib/api';

/**
 * 유휴토지 지도 (SPEC 4.4).
 *
 * ## 왜 타일 지도가 아니라 좌표 SVG 인가
 *
 * 이 화면은 정적 내보내기(`output: 'export'`)된 뒤 FastAPI 컨테이너가 서빙하고,
 * 검증(`docker-compose.test.yml`)은 **외부 네트워크 없이** 도는 것이 전제다.
 * Leaflet·MapLibre 같은 지도 라이브러리 자체는 정적 내보내기에서도 쓸 수 있지만,
 * 실제로 지도가 보이려면 타일 제공자(OSM·Mapbox 등)에 매번 HTTP 요청이 나가고
 * 대부분 API 키를 요구한다. 오프라인 데모에서는 타일이 비어 회색 판만 남는다.
 *
 * 그래서 기본 지도는 **좌표계 자체**로 그린다 — 위경도 격자(그라티큘), 축척 막대,
 * 지역 기준점. 필지는 백엔드 GeoJSON(`GET /api/parcels/geojson`)의 좌표를
 * 등장방형(equirectangular) 투영으로 찍는다. 위경도가 그대로 보이므로 실제 지도와
 * 겹쳐 볼 수 있고, 네트워크가 없어도 항상 같은 그림이 나온다.
 *
 * 타일 배경을 붙이고 싶으면 이 컴포넌트의 `<image>` 한 장을 격자 아래에 깔면
 * 되지만, 그 순간 오프라인 보장이 깨진다는 점을 기억할 것.
 *
 * 자세한 배경은 `docs/map-rendering.md`.
 */

/** 지도에 찍히는 필지 하나 */
export interface ParcelMapPoint {
  id: number;
  name: string;
  lat: number;
  lon: number;
  /** 상태 색 — 백엔드가 `condition` 에서 정해 준다 */
  color: ParcelColor;
  statusLabel: string;
  conditionLabel: string;
  /** 조건 비교 순위 (있으면 마커에 표시) */
  rank?: number;
  /** 필터에서 제외돼 흐리게 표시 */
  muted?: boolean;
}

/** 배경 맥락용 기준점 (시군구 중심 등) */
export interface MapContextPoint {
  id: number;
  name: string;
  lat: number;
  lon: number;
}

const VIEW_W = 400;
const VIEW_H = 300;
const PAD = 34;
/** 그라티큘 간격 후보 (도) — 화면에 4~8줄이 남는 값을 고른다 */
const GRID_STEPS = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1];

function niceStep(span: number): number {
  return GRID_STEPS.find((step) => span / step <= 8) ?? GRID_STEPS[GRID_STEPS.length - 1];
}

function ticks(min: number, max: number, step: number): number[] {
  const out: number[] = [];
  const first = Math.ceil(min / step) * step;
  for (let value = first; value <= max + 1e-9; value += step) {
    out.push(Number(value.toFixed(6)));
  }
  return out;
}

/** 축척 막대에 쓸 "보기 좋은" 거리(km) — 주어진 길이를 넘지 않는 값 */
function niceDistance(km: number): number {
  const candidates = [1, 2, 5, 10, 20, 50, 100, 200];
  return [...candidates].reverse().find((value) => value <= km) ?? candidates[0];
}

interface Projection {
  x: (lon: number) => number;
  y: (lat: number) => number;
  latMin: number;
  latMax: number;
  lonMin: number;
  lonMax: number;
  /** viewBox 1 단위가 몇 km 인가 (가로 기준) */
  kmPerUnit: number;
}

/**
 * 등장방형 투영. 경도는 중심 위도의 cos 로 줄여 실제 거리 비율을 맞춘다.
 * 좁은 지역(시군구 몇 개)에서는 이 정도면 왜곡이 눈에 띄지 않는다.
 */
function project(points: readonly { lat: number; lon: number }[]): Projection {
  const lats = points.map((p) => p.lat);
  const lons = points.map((p) => p.lon);
  // 점이 하나뿐이어도 지도가 무너지지 않도록 최소 폭을 준다.
  const spanLat = Math.max(Math.max(...lats) - Math.min(...lats), 0.02);
  const spanLon = Math.max(Math.max(...lons) - Math.min(...lons), 0.02);
  const midLat = (Math.max(...lats) + Math.min(...lats)) / 2;
  const midLon = (Math.max(...lons) + Math.min(...lons)) / 2;

  const marginLat = spanLat * 0.25;
  const marginLon = spanLon * 0.25;
  const latMin = midLat - spanLat / 2 - marginLat;
  const latMax = midLat + spanLat / 2 + marginLat;
  const lonMin = midLon - spanLon / 2 - marginLon;
  const lonMax = midLon + spanLon / 2 + marginLon;

  const cos = Math.cos((midLat * Math.PI) / 180);
  const unitW = (lonMax - lonMin) * cos;
  const unitH = latMax - latMin;
  const scale = Math.min((VIEW_W - PAD * 2) / unitW, (VIEW_H - PAD * 2) / unitH);
  const offsetX = (VIEW_W - unitW * scale) / 2;
  const offsetY = (VIEW_H - unitH * scale) / 2;

  const kmPerDegLat = haversineKm({ lat: midLat, lon: midLon }, { lat: midLat + 1, lon: midLon });

  return {
    x: (lon) => offsetX + (lon - lonMin) * cos * scale,
    y: (lat) => offsetY + (latMax - lat) * scale,
    latMin,
    latMax,
    lonMin,
    lonMax,
    kmPerUnit: kmPerDegLat / scale,
  };
}

const formatLat = (value: number) => `${formatNumber(value, 2)}°N`;
const formatLon = (value: number) => `${formatNumber(value, 2)}°E`;

export function ParcelMap({
  points,
  contextPoints = [],
  selectedId,
  onSelect,
  className,
}: {
  points: readonly ParcelMapPoint[];
  contextPoints?: readonly MapContextPoint[];
  selectedId?: number | null;
  onSelect?: (parcelId: number) => void;
  className?: string;
}) {
  const titleId = useId();

  // 화면 범위는 **필지 기준**이다. 지역 기준점까지 넣으면 멀리 있는 시군구 하나가
  // 지도를 넓혀 필지들이 한 점에 뭉친다.
  const projection = useMemo(() => {
    if (points.length > 0) return project(points);
    if (contextPoints.length > 0) return project(contextPoints);
    return project([{ lat: 36.2, lon: 127.1 }]);
  }, [points, contextPoints]);

  // 범위 밖의 기준점은 그리지 않는다 (SVG 밖으로 밀려 라벨만 잘려 보인다).
  const visibleContext = contextPoints.filter(
    (point) =>
      point.lat >= projection.latMin &&
      point.lat <= projection.latMax &&
      point.lon >= projection.lonMin &&
      point.lon <= projection.lonMax,
  );

  const latStep = niceStep(projection.latMax - projection.latMin);
  const lonStep = niceStep(projection.lonMax - projection.lonMin);
  const latTicks = ticks(projection.latMin, projection.latMax, latStep);
  const lonTicks = ticks(projection.lonMin, projection.lonMax, lonStep);

  const scaleKm = niceDistance((projection.kmPerUnit * (VIEW_W - PAD * 2)) / 4);
  const scaleUnits = scaleKm / projection.kmPerUnit;

  return (
    <div
      data-testid="parcel-map"
      className={cn('relative w-full overflow-hidden rounded-xl border border-line bg-surface-muted', className)}
    >
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="block h-auto w-full"
        role="group"
        aria-labelledby={titleId}
      >
        <title id={titleId}>
          유휴농지 위치 지도 — 위경도 좌표 위에 필지 {points.length}곳을 상태 색으로 표시
        </title>

        {/* 기본 지도: 위경도 격자 */}
        <rect x={0} y={0} width={VIEW_W} height={VIEW_H} fill="var(--color-surface)" />
        {latTicks.map((lat) => (
          <g key={`lat-${lat}`}>
            <line
              x1={0}
              x2={VIEW_W}
              y1={projection.y(lat)}
              y2={projection.y(lat)}
              stroke="var(--color-line)"
              strokeWidth={0.6}
            />
            <text
              x={3}
              y={projection.y(lat) - 3}
              fontSize={7}
              fill="var(--color-ink-muted)"
              opacity={0.8}
            >
              {formatLat(lat)}
            </text>
          </g>
        ))}
        {lonTicks.map((lon) => (
          <g key={`lon-${lon}`}>
            <line
              x1={projection.x(lon)}
              x2={projection.x(lon)}
              y1={0}
              y2={VIEW_H}
              stroke="var(--color-line)"
              strokeWidth={0.6}
            />
            <text
              x={projection.x(lon) + 3}
              y={VIEW_H - 4}
              fontSize={7}
              fill="var(--color-ink-muted)"
              opacity={0.8}
            >
              {formatLon(lon)}
            </text>
          </g>
        ))}

        {/* 지역 기준점 — 어느 시군구인지 가늠할 맥락 */}
        {visibleContext.map((point) => (
          <g key={`region-${point.id}`} aria-hidden>
            <path
              d={`M${projection.x(point.lon) - 3} ${projection.y(point.lat)} L${projection.x(point.lon)} ${projection.y(point.lat) - 3} L${projection.x(point.lon) + 3} ${projection.y(point.lat)} L${projection.x(point.lon)} ${projection.y(point.lat) + 3} Z`}
              fill="none"
              stroke="var(--color-line-strong)"
              strokeWidth={1}
            />
            <text
              x={projection.x(point.lon)}
              y={projection.y(point.lat) + 12}
              fontSize={7.5}
              textAnchor="middle"
              fill="var(--color-ink-muted)"
            >
              {point.name}
            </text>
          </g>
        ))}

        {/* 축척 막대 */}
        <g aria-hidden transform={`translate(${VIEW_W - PAD - scaleUnits}, ${VIEW_H - 16})`}>
          <line x1={0} x2={scaleUnits} y1={0} y2={0} stroke="var(--color-ink-muted)" strokeWidth={1.2} />
          <line x1={0} x2={0} y1={-3} y2={3} stroke="var(--color-ink-muted)" strokeWidth={1.2} />
          <line x1={scaleUnits} x2={scaleUnits} y1={-3} y2={3} stroke="var(--color-ink-muted)" strokeWidth={1.2} />
          <text x={scaleUnits / 2} y={-5} fontSize={8} textAnchor="middle" fill="var(--color-ink-muted)">
            {formatKm(scaleKm)}
          </text>
        </g>

        {/* 필지 마커 */}
        {points.map((point) => {
          const cx = projection.x(point.lon);
          const cy = projection.y(point.lat);
          const selected = selectedId === point.id;
          const color = COLOR_VARS[point.color];
          return (
            <g
              key={point.id}
              data-testid={`parcel-marker-${point.id}`}
              data-color={point.color}
              data-selected={selected ? 'true' : 'false'}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${point.name} — ${point.statusLabel}, ${point.conditionLabel}`}
              className="cursor-pointer focus:outline-none"
              opacity={point.muted ? 0.3 : 1}
              onClick={() => onSelect?.(point.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect?.(point.id);
                }
              }}
            >
              {selected ? (
                <circle cx={cx} cy={cy} r={11} fill="none" stroke={color} strokeWidth={1.5} opacity={0.7} />
              ) : null}
              <circle cx={cx} cy={cy} r={7} fill={color} stroke="var(--color-surface)" strokeWidth={1.5} />
              {point.rank ? (
                <text
                  x={cx}
                  y={cy + 2.8}
                  fontSize={8}
                  fontWeight={700}
                  textAnchor="middle"
                  fill="var(--color-surface)"
                >
                  {point.rank}
                </text>
              ) : null}
              <text
                x={cx}
                y={cy - 11}
                fontSize={9.5}
                fontWeight={selected ? 700 : 500}
                textAnchor="middle"
                fill="var(--color-ink)"
                stroke="var(--color-surface)"
                strokeWidth={2.5}
                paintOrder="stroke"
              >
                {point.name}
              </text>
            </g>
          );
        })}
      </svg>

      <p className="absolute top-2 right-3 text-[11px] text-ink-muted">
        오프라인 좌표 지도 · 위경도 격자
      </p>
    </div>
  );
}

/** SPEC 4.4 상태 색상 범례 — 색만으로 뜻이 전달되지 않도록 글자를 함께 둔다. */
export function ParcelMapLegend({
  items,
  className,
}: {
  items: readonly { color: ParcelColor; label: string; count: number }[];
  className?: string;
}) {
  return (
    <ul data-testid="map-legend" className={cn('flex flex-wrap items-center gap-x-4 gap-y-2', className)}>
      {items.map((item) => (
        <li key={item.color} className="flex items-center gap-2 text-sm" data-testid={`legend-${item.color}`}>
          <span
            aria-hidden
            className="size-3 shrink-0 rounded-full"
            style={{ backgroundColor: COLOR_VARS[item.color] }}
          />
          <span>{item.label}</span>
          <span className="numeric text-ink-muted">{item.count}곳</span>
        </li>
      ))}
    </ul>
  );
}
