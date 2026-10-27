import { useAgentStore } from "@/stores/agentStore";
import { TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useId } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "./useAppMessage";

type Save = () => Promise<void | boolean>;

/** Debounce edits, serialize writes, and flush the latest job on navigation. */
export function useAutoSave(save: Save, delay = 1000, enabled = true) {
  const { message, modal } = useAppMessage();
  const { t } = useTranslation();
  const errorKey = useId();
  const revision = useRef(0);
  const latest = useRef(save);
  const feedback = useRef({ message, modal, t });
  const pending = useRef(false);
  const running = useRef<Promise<boolean> | null>(null);
  const closing = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useLayoutEffect(() => {
    latest.current = save;
    feedback.current = { message, modal, t };
  });
  const flush = useCallback(async (): Promise<boolean> => {
    clearTimeout(timer.current);
    if (running.current) return running.current;
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
    running.current = run().then((saved) => {
      running.current = null;
      if (!saved && taskRevision === revision.current) pending.current = true;
      if (pending.current && taskRevision !== revision.current) return flush();
      return saved;
    });
    return running.current;
  }, [errorKey]);
  const schedule = useCallback(() => {
    if (!enabled) return;
    revision.current += 1;
    feedback.current.message.destroy(errorKey);
    pending.current = true;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void flush();
    }, delay);
  }, [delay, enabled, flush, errorKey]);
  const discard = useCallback(() => {
    revision.current += 1;
    pending.current = false;
    clearTimeout(timer.current);
    feedback.current.message.destroy(errorKey);
  }, [errorKey]);
  const requestClose = useCallback(
    (onClose: () => void | Promise<void>): Promise<void> => {
      if (closing.current) return closing.current;
      // Keep mobile confirmation inside the sheet's focus trap.
      const container =
        document.activeElement?.closest<HTMLElement>("[data-vaul-drawer]");
      const close = async () => {
        if (!(await flush())) {
          const { modal, t } = feedback.current;
          const confirmed = await new Promise<boolean>((resolve) => {
            modal.confirm({
              centered: true,
              getContainer: container ?? undefined,
              icon: (
                <TriangleAlert
                  size={22}
                  aria-hidden
                  style={{ flexShrink: 0, marginInlineEnd: 16 }}
                />
              ),
              title: t("common.discardChangesTitle"),
              content: t("common.discardChangesContent"),
              okText: t("common.discardAndClose"),
              okButtonProps: { danger: true },
              cancelText: t("common.keepEditing"),
              autoFocusButton: "cancel",
              onOk: () => resolve(true),
              onCancel: () => resolve(false),
              afterClose: () => resolve(false),
            });
          });
          if (!confirmed) return;
          discard();
        }
        await onClose();
      };
      closing.current = close().finally(() => {
        closing.current = null;
      });
      return closing.current;
    },
    [discard, flush],
  );
  useEffect(() => {
    if (!enabled) return;
    return useAgentStore.subscribe((next, previous) => {
      if (next.selectedAgent !== previous.selectedAgent) void flush();
    });
  }, [enabled, flush]);
  useEffect(() => {
    if (!enabled) return;
    return () => {
      void flush();
    };
  }, [enabled, flush]);
  return { schedule, flush, discard, requestClose };
}
