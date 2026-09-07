import { AppShell } from '@/components/AppShell';
import { ConnectionFlow } from '@/components/home/ConnectionFlow';
import { EntryCards } from '@/components/home/EntryCards';
import { RoleMenu } from '@/components/home/RoleMenu';

/**
 * 홈 화면 (SPEC 4.1).
 *
 * - 메뉴 선택: 농가 대시보드 / 유통업체 대시보드 / 유휴토지 지도
 * - 농가 ↔ 유통업체 ↔ 유휴농지 연결 과정 시각화
 * - 사용자 유형별 맞춤 메뉴
 */
export default function HomePage() {
  return (
    <AppShell
      title="울퉁불퉁 농장 AI"
      description="휴경농지·스마트팜·농산물 유통 데이터를 하나로 묶어, AI가 시세를 예측하고 최적의 도매처·판매처·농지를 추천하는 생산-유통 통합 플랫폼입니다."
    >
      <section aria-labelledby="menu-heading">
        <h2 id="menu-heading" className="sr-only">
          메뉴 선택
        </h2>
        <EntryCards />
      </section>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <ConnectionFlow className="lg:col-span-2" />
        <RoleMenu />
      </div>
    </AppShell>
  );
}
