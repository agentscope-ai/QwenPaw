import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  planApi,
  subscribePlanUpdates,
  type PlanStateResponse,
} from "../../api/modules/plan";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PlanPanelProps {
  open: boolean;
  onClose: () => void;
}

const STATE_ICONS: Record<string, string> = {
  done: "✅",
  in_progress: "🔄",
  abandoned: "⛔",
  todo: "⬜",
};

const STATE_COLOR: Record<string, string> = {
  todo: "text-muted-foreground",
  in_progress: "text-orange-500",
  done: "text-green-600",
  abandoned: "text-destructive",
};

/**
 * Read the console channel session ID that the backend actually uses.
 */
function getBackendSessionId(): string {
  return (window as any).currentSessionId || "";
}

const PlanPanel: React.FC<PlanPanelProps> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const [plan, setPlan] = useState<PlanStateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const unsubRef = useRef<(() => void) | null>(null);
  // Track the latest plan provided by SSE so polling cannot overwrite it
  // with a stale null response.
  const ssePlanRef = useRef<PlanStateResponse | null>(null);

  const fetchPlan = useCallback(async () => {
    const sid = getBackendSessionId();
    setLoading(true);
    try {
      const data = await planApi.getCurrentPlan(sid || undefined);
      if (ssePlanRef.current !== null && data === null) return;
      setPlan(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch plan when panel opens
  useEffect(() => {
    if (open) {
      ssePlanRef.current = null;
      fetchPlan();
    }
  }, [open, fetchPlan]);

  // Subscribe to SSE when panel is open
  useEffect(() => {
    if (!open) {
      unsubRef.current?.();
      unsubRef.current = null;
      return;
    }

    const unsub = subscribePlanUpdates((updatedPlan, eventSessionId) => {
      const mySid = getBackendSessionId();
      if (eventSessionId && mySid && eventSessionId !== mySid) return;
      ssePlanRef.current = updatedPlan;
      setPlan(updatedPlan);
    });
    unsubRef.current = unsub;

    return () => {
      unsub();
      unsubRef.current = null;
    };
  }, [open]);

  // Polling fallback every 5s when open
  useEffect(() => {
    if (!open) return;
    const interval = setInterval(fetchPlan, 5000);
    return () => clearInterval(interval);
  }, [open, fetchPlan]);

  const doneCount =
    plan?.subtasks.filter((s) => s.state === "done" || s.state === "abandoned")
      .length ?? 0;
  const totalCount = plan?.subtasks.length ?? 0;
  const percent =
    totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[380px] p-0 flex flex-col">
        <SheetHeader className="flex flex-row items-center justify-between px-4 py-3 border-b shrink-0">
          <SheetTitle className="text-base font-semibold">
            {t("plan.title", "Plan")}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {t("plan.title", "Plan")}
          </SheetDescription>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
          >
            <ChevronRight size={16} />
          </Button>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4">
          {loading && !plan ? (
            <div className="flex items-center justify-center h-32">
              <Loader2
                size={24}
                className="animate-spin text-muted-foreground"
              />
            </div>
          ) : !plan ? (
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground text-sm">
              <span className="text-3xl">📋</span>
              <div>{t("plan.noPlan", "No active plan")}</div>
              <div className="text-xs text-center">
                {t(
                  "plan.noPlanHint",
                  "Use /plan <description> to create a plan",
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {/* Plan info */}
              <div>
                <div className="flex items-center gap-2 font-medium">
                  <span>{plan.name}</span>
                  <span
                    className={cn(
                      "text-xs px-1.5 py-0.5 rounded-full bg-muted",
                      STATE_COLOR[plan.state] || "text-muted-foreground",
                    )}
                  >
                    {t(`plan.state.${plan.state}`, plan.state)}
                  </span>
                </div>
                {plan.description && (
                  <div className="text-sm text-muted-foreground mt-1">
                    {plan.description}
                  </div>
                )}
              </div>

              {/* Progress bar */}
              <div>
                <div className="flex justify-between text-xs text-muted-foreground mb-1">
                  <span>{t("plan.progress", "Progress")}</span>
                  <span>
                    {doneCount}/{totalCount}
                  </span>
                </div>
                <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      plan.state === "abandoned"
                        ? "bg-destructive"
                        : "bg-primary",
                    )}
                    style={{ width: `${percent}%` }}
                  />
                </div>
              </div>

              {/* Subtask list */}
              <ul className="flex flex-col gap-2">
                {plan.subtasks.map((subtask, idx) => (
                  <li key={idx} className="flex gap-2 items-start">
                    <span className="text-base shrink-0 mt-0.5">
                      {STATE_ICONS[subtask.state] || "⬜"}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{subtask.name}</div>
                      {subtask.description && (
                        <div className="text-xs text-muted-foreground">
                          {subtask.description}
                        </div>
                      )}
                      {subtask.outcome && (
                        <div className="text-xs text-green-600 dark-mode:text-green-400 mt-0.5">
                          ✓ {subtask.outcome}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>

              {plan.outcome && (
                <div className="text-sm border-t pt-3 mt-1">
                  <strong>{t("plan.outcome", "Outcome")}:</strong>{" "}
                  {plan.outcome}
                </div>
              )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
};

export default PlanPanel;
