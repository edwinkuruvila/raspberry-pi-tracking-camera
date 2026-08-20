import { getJson, notifyIfUnauthorized } from "./client";

export type PiCheck = { ok: boolean; detail: string; latency_ms: number | null };
export type PiHealth = { ok: boolean; checks: { stream_http: PiCheck } };
export type PublicConfig = { public_stream_url: string };

export function getPiHealth(): Promise<PiHealth> {
  return getJson<PiHealth>("/api/pi/health");
}

export function getPublicConfig(): Promise<PublicConfig> {
  return getJson<PublicConfig>("/api/config");
}

export async function ensureStreamSession(): Promise<void> {
  const response = await fetch("/api/stream/session");
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new Error(`${response.status} ${response.statusText}`);
  }
}
