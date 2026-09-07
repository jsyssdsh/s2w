import type { Metadata, Viewport } from 'next';
import { RoleProvider } from '@/components/RoleProvider';
import { SiteFooter } from '@/components/SiteFooter';
import { SiteHeader } from '@/components/SiteHeader';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: '울퉁불퉁 농장 AI',
    template: '%s · 울퉁불퉁 농장 AI',
  },
  description:
    '휴경농지·스마트팜·농산물 유통 데이터를 하나로 묶어 시세를 예측하고 최적의 거래처를 추천하는 생산-유통 통합 플랫폼',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body className="min-h-screen antialiased">
        <RoleProvider>
          <div className="flex min-h-screen flex-col">
            <a
              href="#main"
              className="sr-only focus:not-sr-only focus:absolute focus:z-20 focus:m-2 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2"
            >
              본문으로 건너뛰기
            </a>
            <SiteHeader />
            <main id="main" className="flex-1">
              {children}
            </main>
            <SiteFooter />
          </div>
        </RoleProvider>
      </body>
    </html>
  );
}
