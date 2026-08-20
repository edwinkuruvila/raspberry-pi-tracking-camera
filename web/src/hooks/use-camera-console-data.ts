import { useEffect, useState } from "react";

import { ensureStreamSession, getPiHealth, getPublicConfig, type PiHealth } from "@/api";

type LoadState = "loading" | "ready" | "error";

type CameraConsoleData = {
  piHealth: PiHealth | null;
  checkedAt: Date | null;
  state: LoadState;
  error: string | null;
  streamUrl: string | null;
};

const POLL_INTERVAL_MS = 30000;
const STREAM_SESSION_REFRESH_INTERVAL_MS = 60000;

export function useCameraConsoleData(): CameraConsoleData {
  const [piHealth, setPiHealth] = useState<PiHealth | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    function setLoadError(err: unknown) {
      if (!cancelled) {
        setError(err instanceof Error ? err.message : "Unknown error");
        setState("error");
      }
    }

    async function loadInitialData() {
      try {
        const [nextPiHealth, , publicConfig] = await Promise.all([
          getPiHealth(),
          ensureStreamSession(),
          getPublicConfig(),
        ]);

        if (!cancelled) {
          setPiHealth(nextPiHealth);
          setStreamUrl(publicConfig.public_stream_url);
          setCheckedAt(new Date());
          setState("ready");
          setError(null);
        }
      } catch (err) {
        setLoadError(err);
      }
    }

    async function refreshHealth() {
      try {
        const nextPiHealth = await getPiHealth();
        if (!cancelled) {
          setPiHealth(nextPiHealth);
          setCheckedAt(new Date());
          setState("ready");
          setError(null);
        }
      } catch (err) {
        setLoadError(err);
      }
    }

    async function refreshStreamSession() {
      try {
        await ensureStreamSession();
      } catch (err) {
        setLoadError(err);
      }
    }

    void loadInitialData();
    const healthIntervalId = window.setInterval(() => void refreshHealth(), POLL_INTERVAL_MS);
    const sessionIntervalId = window.setInterval(() => void refreshStreamSession(), STREAM_SESSION_REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(healthIntervalId);
      window.clearInterval(sessionIntervalId);
    };
  }, []);

  return { piHealth, checkedAt, state, error, streamUrl };
}
