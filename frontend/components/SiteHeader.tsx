'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/cn';
import { NAV_ITEMS, ROLES, ROLE_LABELS, type Role } from '@/lib/roles';
import { Select } from '@/components/ui';
import { useRole } from '@/components/RoleProvider';

const ROLE_OPTIONS = ROLES.map((role) => ({ value: role, label: ROLE_LABELS[role] }));

/**
 * 앱 헤더 — 앱 이름, 반응형 내비게이션, 역할 전환기 (SPEC 4.1).
 *
 * 좁은 화면(375px)에서는 메뉴가 헤더 아래 줄로 내려가 가로 스크롤한다.
 * 별도의 햄버거 다이얼로그를 쓰지 않아 메뉴가 항상 한 번에 보인다.
 */
export function SiteHeader() {
  const pathname = usePathname();
  const { role, setRole } = useRole();

  const isActive = (href: string) => pathname === href || pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-10 border-b border-line bg-surface/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span aria-hidden className="text-lg">🌱</span>
          <span>울퉁불퉁 농장 AI</span>
        </Link>

        <nav aria-label="주요 메뉴" className="order-3 -mx-4 w-full overflow-x-auto px-4 md:order-2 md:mx-0 md:w-auto md:flex-1 md:overflow-visible md:px-0">
          <ul className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive(item.href) ? 'page' : undefined}
                  className={cn(
                    'inline-block rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-colors',
                    isActive(item.href)
                      ? 'bg-accent-soft font-medium text-accent'
                      : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
                  )}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <div className="order-2 ml-auto md:order-3 md:ml-0">
          <Select
            label="사용자 유형"
            hideLabel
            data-testid="role-switcher"
            aria-label="사용자 유형 선택"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            options={ROLE_OPTIONS}
          />
        </div>
      </div>
    </header>
  );
}
