import { cn } from '@/lib/cn';
import { Card } from '@/components/ui';

/**
 * 농가 ↔ 유통업체 ↔ 유휴농지 연결 과정 시각화 (SPEC 4.1 향후 수정 계획).
 *
 * 좁은 화면에서는 세로로 쌓이고 넓은 화면에서는 가로로 이어진다.
 * 화살표는 장식이므로 스크린리더에서 숨기고, 흐름 설명은 글로 남긴다.
 */
interface FlowNode {
  icon: string;
  title: string;
  caption: string;
  tone: string;
}

const NODES: readonly FlowNode[] = [
  {
    icon: '🗺️',
    title: '유휴농지',
    caption: '휴경지 조건·적합도 매칭',
    tone: 'bg-info-soft text-info',
  },
  {
    icon: '🌱',
    title: '농가',
    caption: '스마트팜 생산·출하',
    tone: 'bg-good-soft text-good',
  },
  {
    icon: '🚚',
    title: '유통업체',
    caption: '매입·재고·판매처 연계',
    tone: 'bg-warn-soft text-warn',
  },
];

const LINKS: readonly { forward: string; backward: string }[] = [
  { forward: '농지 추천 · 임대 신청', backward: '재배 이력 · 생육 데이터' },
  { forward: '출하 물량 · 품질 등급', backward: 'AI 추천 도매처 · 권장 거래가' },
];

export function ConnectionFlow({ className }: { className?: string }) {
  return (
    <Card className={cn('overflow-hidden', className)} data-testid="connection-flow">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-base font-semibold tracking-tight">연결 과정 한눈에 보기</h2>
        <p className="mt-1 text-sm text-ink-muted">
          유휴농지를 신규 농업인에게 잇고, 그 위에서 자란 농산물을 가장 수익성 높은
          유통 경로로 연결합니다. 가운데의 AI가 시세를 예측하고 거래처를 추천합니다.
        </p>
      </div>

      <div className="px-5 py-6">
        <ol className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
          {NODES.map((node, index) => (
            <li key={node.title} className="contents">
              <div className="flex flex-1 items-center gap-3 rounded-xl border border-line bg-surface-muted/60 px-4 py-3 md:flex-col md:text-center">
                <span
                  aria-hidden
                  className={cn(
                    'flex size-11 shrink-0 items-center justify-center rounded-full text-xl',
                    node.tone,
                  )}
                >
                  {node.icon}
                </span>
                <span className="min-w-0">
                  <span className="block font-semibold">{node.title}</span>
                  <span className="block text-xs text-ink-muted">{node.caption}</span>
                </span>
              </div>

              {index < LINKS.length ? (
                <div className="flex shrink-0 flex-col items-center gap-0.5 px-2 text-center md:w-40">
                  <span className="text-[0.6875rem] leading-tight text-ink-muted">
                    {LINKS[index].forward}
                  </span>
                  <span aria-hidden className="text-accent">
                    <span className="md:hidden">↕</span>
                    <span className="hidden md:inline">⇄</span>
                  </span>
                  <span className="text-[0.6875rem] leading-tight text-ink-muted">
                    {LINKS[index].backward}
                  </span>
                </div>
              ) : null}
            </li>
          ))}
        </ol>

        <p className="mt-5 rounded-lg bg-accent-soft px-4 py-3 text-sm leading-relaxed text-accent">
          <span className="font-semibold">AI</span> — 과거 시세·거래량·기상 데이터로 출하일별
          예상 가격을 계산하고, 운송비와 수수료까지 반영한 예상 순수익 순으로 도매처와 농지를
          추천합니다.
        </p>
      </div>
    </Card>
  );
}
