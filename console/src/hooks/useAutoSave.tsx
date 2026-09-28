import { useAgentStore } from "@/stores/agentStore";
import { useCallback, useEffect, useLayoutEffect, useRef, useId } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "./useAppMessage";

type Save = () => Promise<void | boolean>;

/** Debounce edits, serialize writes, and flush the latest job on navigation. */
export function useAutoSave(save: Save, delay = 1000) {
  const { message } = useAppMessage();
  const { t } = useTranslation();
  const errorKey = useId();
  const revision = useRef(0);
  const latest = useRef(save);
  const feedback = useRef({ message, t });
  const pending = useRef(false);
  const running = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useLayoutEffect(() => {
    latest.current = save;
    feedback.current = { message, t };
  });
  const flush = useCallback(async (): Promise<boolean> => {
    clearTimeout(timer.current);
    if (running.current) {
      const saved = await running.current;
      if (!pending.current) return saved;
    }
    if (!pending.current) return true;
    pending.current = false;
    const task = latest.current;
    const taskRevision = revision.current;
    const run = async (): Promise<boolean> => {
      try {
        return (await task()) !== false;
      } catch (error) {
        // Keep the failed job in the retry closure, including after unmount.
        const { message, t } = feedback.current;
        if (taskRevision !== revision.current) return false;
        message.error({
          key: errorKey,
          duration: 0,
          content: (
            <span>
              {t("common.autoSaveFailed")}{" "}
              <button
                type="button"
                onClick={() => {
                  message.destroy(errorKey);
                  if (taskRevision === revision.current) {
                    pending.current = true;
                    void flush();
                  }
                }}
              >
                {t("common.retry")}
              </button>
            </span>
          ),
        });
        console.error("Automatic settings save failed", error);
        return false;
      }
    };
    running.current = run();
    const saved = await running.current;
    running.current = null;
    if (!saved && taskRevision === revision.current) pending.current = true;
    return saved;
  }, [errorKey]);
  const schedule = useCallback(() => {
    revision.current += 1;
    feedback.current.message.destroy(errorKey);
    pending.current = true;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void flush();
    }, delay);
  }, [delay, flush, errorKey]);
  useEffect(
    () =>
      useAgentStore.subscribe((next, previous) => {
        if (next.selectedAgent !== previous.selectedAgent) void flush();
      }),
    [flush],
  );
  useEffect(
    () => () => {
      void flush();
    },
    [flush],
  );
  return { schedule, flush };
}
