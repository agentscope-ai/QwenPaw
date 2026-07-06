import { useEffect } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";

const DIAGNOSTIC_POLL_INTERVAL_MS = 60_000;
const INPUT_LATENCY_THRESHOLD_MS = 100;
const LONGTASK_THRESHOLD_MS = 50;

/**
 * Lightweight frontend diagnostics for the Tauri desktop build.
 *
 * - Logs long JavaScript tasks that block the main thread (likely cause of
 *   "typing lags" in the chat input).
 * - Logs slow input events on editable fields.
 * - Polls the Rust shell for system-level resource pressure and backend
 *   process health.
 *
 * All data is written via console.* so that tauri-plugin-log captures it in
 * the desktop log file (qwenpaw-desktop*.log).
 */
export function useDesktopDiagnostics() {
  useEffect(() => {
    if (!isTauri()) return;

    let longtaskObserver: PerformanceObserver | null = null;
    if ("PerformanceObserver" in window) {
      try {
        longtaskObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            const duration = Math.round(entry.duration);
            if (duration >= LONGTASK_THRESHOLD_MS) {
              console.warn(
                `[frontend-diagnostics] long task detected: ${duration}ms`,
                entry.toJSON(),
              );
            }
          }
        });
        longtaskObserver.observe({ entryTypes: ["longtask"] });
      } catch {
        // longtask observer not supported in this WebView.
      }
    }

    const handleBeforeInput = (e: Event) => {
      const target = e.target as HTMLElement | null;
      if (
        !target ||
        (target.tagName !== "TEXTAREA" && target.tagName !== "INPUT")
      ) {
        return;
      }
      const start = performance.now();
      const measure = () => {
        const elapsed = performance.now() - start;
        if (elapsed >= INPUT_LATENCY_THRESHOLD_MS) {
          console.warn(
            `[frontend-diagnostics] slow input on ${
              target.tagName
            }: ${Math.round(elapsed)}ms`,
          );
        }
      };
      requestAnimationFrame(() => requestAnimationFrame(measure));
    };
    document.addEventListener("beforeinput", handleBeforeInput, true);

    const logDiagnostics = async () => {
      try {
        const snapshot = await invoke<{
          log_dir?: string;
          cpu_usage_percent: number;
          memory_usage_percent: number;
          total_memory_bytes: number;
          used_memory_bytes: number;
          backend_process?: {
            pid: number;
            memory_bytes: number;
            cpu_usage_percent: number;
            name: string;
          };
        }>("get_system_diagnostics");

        console.info(
          `[frontend-diagnostics] system cpu=${snapshot.cpu_usage_percent.toFixed(
            1,
          )}% ` +
            `memory=${snapshot.memory_usage_percent.toFixed(1)}% ` +
            `log_dir=${snapshot.log_dir ?? "unknown"} ` +
            `backend=${
              snapshot.backend_process
                ? `pid=${snapshot.backend_process.pid} mem=${(
                    snapshot.backend_process.memory_bytes / 1_048_576
                  ).toFixed(
                    1,
                  )}MB cpu=${snapshot.backend_process.cpu_usage_percent.toFixed(
                    1,
                  )}%`
                : "none"
            }`,
        );
      } catch (err) {
        console.error(
          "[frontend-diagnostics] failed to fetch diagnostics:",
          err,
        );
      }
    };

    logDiagnostics();
    const interval = setInterval(logDiagnostics, DIAGNOSTIC_POLL_INTERVAL_MS);

    return () => {
      longtaskObserver?.disconnect();
      document.removeEventListener("beforeinput", handleBeforeInput, true);
      clearInterval(interval);
    };
  }, []);
}
