import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '울퉁불퉁 농장 AI',
  description:
    '휴경농지·스마트팜·농산물 유통 데이터를 하나로 묶어 시세를 예측하고 최적의 거래처를 추천하는 생산-유통 통합 플랫폼',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
