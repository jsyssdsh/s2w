/**
 * 유휴토지 화면(SPEC 4.4 / 4.5)이 공유하는 표시 규약.
 *
 * 상태 색(녹/황/적)은 백엔드가 `condition` 에서 이미 정해 내려준다
 * (`docs/API.md` 의 `ParcelFeatureProperties`). 프론트는 그 값을 디자인 시스템의
 * 시맨틱 토큰으로 옮기기만 한다 — 하드코딩된 hex 를 화면에 쓰지 않아야
 * 다크 모드에서도 대비가 유지된다.
 */

import type { BadgeTone, FarmStatus } from '@/components/ui';
import type { ParcelColor, ParcelCondition, ParcelStatus } from '@/lib/api';

/** 백엔드의 3단계 상태를 디자인 시스템의 `FarmStatus` 로 옮긴다. */
export const CONDITION_STATUS: Record<ParcelCondition, FarmStatus> = {
  best: 'best',
  good: 'fair',
  needs_improvement: 'poor',
};

export const COLOR_TONES: Record<ParcelColor, BadgeTone> = {
  green: 'good',
  amber: 'warn',
  red: 'bad',
};

/** 지도 마커·범례가 쓰는 CSS 변수 (라이트/다크 자동 전환) */
export const COLOR_VARS: Record<ParcelColor, string> = {
  green: 'var(--color-good)',
  amber: 'var(--color-warn)',
  red: 'var(--color-bad)',
};

export const STATUS_TONES: Record<ParcelStatus, BadgeTone> = {
  idle: 'neutral',
  operating: 'info',
  converted: 'good',
};

/**
 * 상세 화면 경로.
 *
 * 정적 내보내기(`output: 'export'`)라 `/land/[id]` 같은 동적 라우트를 쓰려면
 * 빌드 시점에 필지 id 를 모두 알아야 한다. 필지는 DB 에 있고 빌드 때는 서버가
 * 없으므로, 상세 화면은 **쿼리 파라미터**로 필지를 고른다.
 */
export function parcelDetailHref(parcelId: number): string {
  return `/land/detail/?id=${parcelId}`;
}

/** 두 좌표 사이의 거리(km). 백엔드 `app/services/geo.py` 의 haversine 과 같은 식. */
export function haversineKm(
  a: { lat: number; lon: number },
  b: { lat: number; lon: number },
): number {
  const R = 6371.0088;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
