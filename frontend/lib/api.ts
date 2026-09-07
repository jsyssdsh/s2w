/**
 * The single typed API client. Every screen goes through this module — no
 * bare `fetch` calls in components (docs/ARCHITECTURE.md).
 *
 * The exported site is served by the same FastAPI process that answers /api,
 * so the default base URL is relative. Point NEXT_PUBLIC_API_BASE_URL at a
 * running backend when developing the frontend standalone.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? '';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}/api${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `GET /api${path} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE_URL}/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, `POST /api${path} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Shared shapes returned by the reference endpoints. */
export interface Region {
  id: number;
  name: string;
  lat: number;
  lon: number;
}

export interface Crop {
  id: number;
  name: string;
  unit: string;
}

export const getHealth = () => apiGet<{ status: string }>('/health');
export const getRegions = () => apiGet<Region[]>('/regions');
export const getCrops = () => apiGet<Crop[]>('/crops');
