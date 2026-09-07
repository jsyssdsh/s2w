import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // The FastAPI container serves the exported site from /app/static.
  output: 'export',
  // No Next.js image optimizer exists behind a static export.
  images: { unoptimized: true },
  // Emit <route>/index.html so any path resolves without a rewrite rule.
  trailingSlash: true,
};

export default nextConfig;
