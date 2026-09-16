import { useEffect } from "react";
import { getApiUrl } from "../api/config";
import { buildAuthHeaders } from "../api/authHeaders";

/** Signal real page use to the local Runtime, never directly to telemetry. */
export function RuntimeActivity() {
  useEffect(() => {
    let pending = false;
    let reportedDay = "";
    let retryAfter = 0;
    let controller: AbortController | undefined;

    const report = () => {
      const day = new Date().toISOString().slice(0, 10);
      if (
        document.visibilityState !== "visible" ||
        reportedDay === day ||
        pending ||
        Date.now() < retryAfter
      ) {
        return;
      }
      pending = true;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 2_000);
      // Do not use request(): a telemetry failure must not log the user out.
      void fetch(getApiUrl("/telemetry/activity"), {
        method: "POST",
        headers: buildAuthHeaders(),
        signal: controller.signal,
      })
        .then((response) => {
          if (response.status === 204) reportedDay = day;
        })
        .catch(() => undefined)
        .finally(() => {
          window.clearTimeout(timeout);
          pending = false;
          retryAfter = Date.now() + 60_000;
        });
    };
    const onInteraction = (event: Event) => {
      if (event.isTrusted) report();
    };
    report();
    document.addEventListener("pointerdown", onInteraction, true);
    document.addEventListener("keydown", onInteraction, true);
    // There is deliberately no timer or visibility-only cross-day heartbeat.
    return () => {
      controller?.abort();
      document.removeEventListener("pointerdown", onInteraction, true);
      document.removeEventListener("keydown", onInteraction, true);
    };
  }, []);
  return null;
}
