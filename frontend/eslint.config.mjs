import coreWebVitals from 'eslint-config-next/core-web-vitals';
import typescript from 'eslint-config-next/typescript';

/** Next.js 권장 규칙 + 타입스크립트. `npm run lint` 이 이 설정을 쓴다. */
const config = [
  { ignores: ['.next/**', 'out/**', 'next-env.d.ts'] },
  ...coreWebVitals,
  ...typescript,
];

export default config;
