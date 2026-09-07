# E2E runner. The base image ships the browsers for Playwright 1.52, so
# test/package.json must stay pinned to the matching @playwright/test.
FROM mcr.microsoft.com/playwright:v1.52.0-jammy

WORKDIR /work

# Install deps first so the layer caches across spec edits. Without this the
# runner would fall back to `npx`, which fetches a floating playwright release
# and cannot resolve @playwright/test at all.
COPY package.json package-lock.json ./
RUN npm ci

COPY playwright.config.ts global-setup.ts ./
COPY specs/ specs/

CMD ["npx", "playwright", "test"]
