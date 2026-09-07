'use client';

import { createContext, useContext, useMemo, useSyncExternalStore } from 'react';
import { DEFAULT_ROLE, isRole, type Role } from '@/lib/roles';

const STORAGE_KEY = 'farmflow.role';

/**
 * 사용자 유형 상태 (SPEC 4.1 "사용자 유형별 맞춤 메뉴").
 *
 * 로그인이 없는 프로토타입이라 선택값을 localStorage 에 둔다. 정적 내보내기라
 * 빌드 시점 HTML 은 항상 기본값으로 렌더되므로, 저장값은 외부 스토어로 읽어
 * 하이드레이션 이후에 반영한다.
 */
const listeners = new Set<() => void>();
let cached: Role | null = null;

function read(): Role {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isRole(stored) ? stored : DEFAULT_ROLE;
  } catch {
    // 사생활 보호 모드 등에서 접근이 막히면 기본값으로 둔다.
    return DEFAULT_ROLE;
  }
}

function getSnapshot(): Role {
  cached ??= read();
  return cached;
}

/** 빌드 시점(그리고 하이드레이션 첫 렌더)의 값 */
function getServerSnapshot(): Role {
  return DEFAULT_ROLE;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  // 다른 탭에서 유형을 바꾸면 따라간다.
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) {
      cached = null;
      onChange();
    }
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener('storage', onStorage);
  };
}

function writeRole(next: Role): void {
  cached = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // 저장에 실패해도 이번 세션 동안은 동작한다.
  }
  for (const listener of listeners) listener();
}

interface RoleContextValue {
  role: Role;
  setRole: (role: Role) => void;
}

const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({ children }: { children: React.ReactNode }) {
  const role = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const value = useMemo(() => ({ role, setRole: writeRole }), [role]);
  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const context = useContext(RoleContext);
  if (!context) throw new Error('useRole 은 RoleProvider 안에서만 쓸 수 있습니다.');
  return context;
}
