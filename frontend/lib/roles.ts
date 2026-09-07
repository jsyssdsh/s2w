/**
 * 사용자 유형과 유형별 메뉴 (SPEC 4.1 "로그인 및 사용자 유형별 맞춤 메뉴").
 *
 * 값은 백엔드 `UserRole` (backend/app/models.py) 과 같은 문자열을 쓴다.
 * 로그인이 붙기 전까지는 헤더의 역할 전환기로 고른 값이 곧 사용자 유형이다.
 */

export const ROLES = ['farmer', 'wholesaler', 'buyer', 'landowner'] as const;

export type Role = (typeof ROLES)[number];

/** 로그인 전 기본 시점 — 모든 메뉴를 보여준다. */
export const DEFAULT_ROLE: Role = 'farmer';

export const ROLE_LABELS: Record<Role, string> = {
  farmer: '농가',
  wholesaler: '유통업체',
  buyer: '판매처',
  landowner: '토지주',
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  farmer: '작물을 재배하고 출하한다',
  wholesaler: '농산물을 매입해 판매처로 넘긴다',
  buyer: '마트·급식·가공·음식점 등 최종 구매처',
  landowner: '휴경농지를 보유하고 임대한다',
};

export interface NavItem {
  href: string;
  label: string;
  /** SPEC 4.x 절 번호 — 화면 설명에 쓴다 */
  spec: string;
  description: string;
  /** 이 메뉴를 주로 쓰는 사용자 유형 */
  roles: readonly Role[];
}

/**
 * 앱 전체의 단일 내비게이션 목록. 헤더 · 홈 화면 카드 · 역할별 메뉴가
 * 모두 이 배열을 읽는다. 새 화면은 여기에 한 줄 추가한다.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: '/farm/',
    label: '농가 대시보드',
    spec: 'SPEC 4.2',
    description: '재배 현황, 예상 수확량, 도매 시세, AI 추천 유통처와 예상 수익률',
    roles: ['farmer', 'landowner'],
  },
  {
    href: '/distributor/',
    label: '유통업체 대시보드',
    spec: 'SPEC 4.3',
    description: '공급 가능 물량, AI 추천 농가와 권장 거래가, 품목별 시장 등락률',
    roles: ['wholesaler', 'buyer'],
  },
  {
    href: '/land/',
    label: '유휴토지 지도',
    spec: 'SPEC 4.4 / 4.5',
    description: '휴경농지 지도와 상태 구분, 농지별 조건 비교와 상세 센서 현황',
    roles: ['farmer', 'landowner', 'wholesaler', 'buyer'],
  },
] as const;

/** 해당 유형에게 우선 노출할 메뉴 */
export function navItemsForRole(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}

export function isRole(value: string | null | undefined): value is Role {
  return !!value && (ROLES as readonly string[]).includes(value);
}
