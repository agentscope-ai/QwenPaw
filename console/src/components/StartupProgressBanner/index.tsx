import { useEffect, useState } from "react";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { buildAuthHeaders } from "../../api/authHeaders";
import { getApiUrl } from "../../api/config";

const POLL_INTERVAL_MS = 1000;
// Stop polling eventually so a stuck backend cannot pin the banner forever.
const MAX_POLL_MS = 120_000;
const LOADING_PHASES = new Set(["plugins", "agents", "finalizing"]);

/**
 * Read the background startup phase from `/api/healthz`.
 *
 * The endpoint answers 503 until core agents are ready, so the body is read
 * for both statuses. Returns null when the backend does not report a phase
 * (older backends) or the probe fails.
 */
async function fetchStartupPhase(): Promise<string | null> {
  const response = await fetch(getApiUrl("/healthz"), {
    headers: buildAuthHeaders(),
  });
  if (response.status !== 200 && response.status !== 503) return null;
  const body = (await response.json()) as { phase?: unknown };
  return typeof body.phase === "string" ? body.phase : null;
}

/**
 * Tells the user the backend is still loading agents, plugins and providers
 * after the console has rendered, instead of leaving half-populated views
 * looking broken (#8115).
 */
export default function StartupProgressBanner() {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();

    const poll = async () => {
      let next: string | null = null;
      try {
        next = await fetchStartupPhase();
      } catch {
        next = null;
      }
      if (cancelled) return;
      const loading =
        next !== null &&
        LOADING_PHASES.has(next) &&
        Date.now() - startedAt < MAX_POLL_MS;
      setPhase(loading ? next : null);
      if (loading) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (!phase) return null;
  return (
    <Alert
      type="info"
      showIcon
      banner
      message={t(`startupProgress.${phase}`)}
    />
  );
}
