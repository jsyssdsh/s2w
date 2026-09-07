/** 프로토타입 표기 — SPEC 4장 서두의 단서를 화면에도 남긴다. */
export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="mx-auto max-w-6xl px-4 py-6 text-xs leading-relaxed text-ink-muted sm:px-6">
        울퉁불퉁 농장 AI — AI 기반 스마트팜 생산·유통 플랫폼 프로토타입.
        화면과 수치는 아이디어를 구체화하기 위한 예시이며 본선 출전 시 수정된
        기능과 디자인을 사용할 예정입니다.
      </div>
    </footer>
  );
}
