'use client';

import Link from 'next/link';
import { useRole } from '@/components/RoleProvider';
import { Card, CardBody, CardHeader } from '@/components/ui';
import { ROLE_DESCRIPTIONS, ROLE_LABELS, navItemsForRole } from '@/lib/roles';

/**
 * 사용자 유형별 맞춤 메뉴 (SPEC 4.1 향후 수정 계획).
 * 유형은 헤더의 역할 전환기에서 고른다.
 */
export function RoleMenu() {
  const { role } = useRole();
  const items = navItemsForRole(role);

  return (
    <Card data-testid="role-menu">
      <CardHeader
        title={`${ROLE_LABELS[role]} 맞춤 메뉴`}
        description={`${ROLE_DESCRIPTIONS[role]} — 이 유형이 자주 쓰는 화면부터 보여줍니다. 헤더에서 유형을 바꿀 수 있습니다.`}
      />
      <CardBody>
        <ul className="divide-y divide-line">
          {items.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-surface-muted"
              >
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{item.label}</span>
                  <span className="block truncate text-xs text-ink-muted">
                    {item.description}
                  </span>
                </span>
                <span aria-hidden className="text-ink-muted">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
