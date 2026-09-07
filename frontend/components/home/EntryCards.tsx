import Link from 'next/link';
import { cn } from '@/lib/cn';
import { NAV_ITEMS, type NavItem } from '@/lib/roles';
import { Badge } from '@/components/ui';

const ICONS: Record<string, string> = {
  '/farm/': '🌾',
  '/distributor/': '📦',
  '/land/': '🗺️',
};

/** SPEC 4.1 의 메뉴 선택 — 농가 대시보드 / 유통업체 대시보드 / 유휴토지 지도. */
export function EntryCards({
  items = NAV_ITEMS,
  className,
}: {
  items?: readonly NavItem[];
  className?: string;
}) {
  return (
    <ul
      data-testid="entry-cards"
      className={cn('grid grid-cols-1 gap-4 md:grid-cols-3', className)}
    >
      {items.map((item) => (
        <li key={item.href}>
          <Link
            href={item.href}
            data-testid={`entry-${item.href.replaceAll('/', '')}`}
            className="group flex h-full flex-col rounded-xl border border-line bg-surface p-5 transition-colors hover:border-accent hover:bg-accent-soft/40"
          >
            <span aria-hidden className="text-2xl">
              {ICONS[item.href] ?? '📊'}
            </span>
            <span className="mt-3 flex items-center gap-2">
              <span className="text-lg font-semibold tracking-tight">{item.label}</span>
              <Badge tone="neutral">{item.spec}</Badge>
            </span>
            <span className="mt-2 flex-1 text-sm leading-relaxed text-ink-muted">
              {item.description}
            </span>
            <span className="mt-4 text-sm font-medium text-accent">
              바로가기 <span aria-hidden className="transition-transform group-hover:translate-x-0.5 inline-block">→</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
