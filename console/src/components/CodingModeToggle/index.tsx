import { useCallback, useState } from "react";
import { Code, FlaskConical, MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useCodingMode, useProjectDir } from "../../stores/codingModeStore";
import { useAgentStore } from "../../stores/agentStore";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { useNavigate } from "react-router-dom";
import ProjectSelectModal from "../ProjectSelectModal";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const CONFIRMED_KEY = "qwenpaw-coding-mode-confirmed";

export default function CodingModeToggle() {
  const { t } = useTranslation();
  const { codingMode, initialized, setCodingMode } = useCodingMode();
  const { selectedAgent } = useAgentStore();
  const navigate = useNavigate();
  const { projectDir } = useProjectDir();
  const [loading, setLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showProjectSelect, setShowProjectSelect] = useState(false);

  const activate = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    try {
      await fetch(getApiUrl("/coding-mode"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(),
          "X-Agent-Id": selectedAgent,
        },
        body: JSON.stringify({ enabled: true }),
      });
      setCodingMode(true);
      navigate("/coding");
    } catch {
      // Silently ignore
    } finally {
      setLoading(false);
    }
  }, [loading, selectedAgent, setCodingMode, navigate]);

  const deactivate = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    try {
      await fetch(getApiUrl("/coding-mode"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(),
          "X-Agent-Id": selectedAgent,
        },
        body: JSON.stringify({ enabled: false }),
      });
      setCodingMode(false);
      navigate("/chat");
    } catch {
      // Silently ignore
    } finally {
      setLoading(false);
    }
  }, [loading, selectedAgent, setCodingMode, navigate]);

  const toggle = useCallback(async () => {
    if (codingMode) {
      await deactivate();
      return;
    }
    const confirmed = localStorage.getItem(CONFIRMED_KEY);
    if (!confirmed) {
      setShowConfirm(true);
    } else if (projectDir === undefined) {
      setShowProjectSelect(true);
    } else {
      await activate();
    }
  }, [codingMode, activate, deactivate, projectDir]);

  const handleConfirm = useCallback(() => {
    localStorage.setItem(CONFIRMED_KEY, "1");
    setShowConfirm(false);
    setShowProjectSelect(true);
  }, []);

  const handleProjectConfirm = useCallback(async () => {
    setShowProjectSelect(false);
    await activate();
  }, [activate]);

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-[5px] px-2.5 py-1 rounded-md border-[1.5px] border-border bg-transparent",
              "text-[13px] font-medium text-muted-foreground cursor-pointer transition-all",
              "hover:enabled:border-primary hover:enabled:text-primary hover:enabled:bg-primary/[0.06]",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "dark-mode:border-white/15 dark-mode:text-white/85",
              "dark-mode:hover:enabled:border-[#4da3ff] dark-mode:hover:enabled:text-[#4da3ff] dark-mode:hover:enabled:bg-[rgba(22,119,255,0.12)]",
              codingMode && [
                "border-primary text-primary bg-primary/[0.08]",
                "dark-mode:border-[#4da3ff] dark-mode:text-[#4da3ff] dark-mode:bg-[rgba(22,119,255,0.18)]",
              ],
            )}
            onClick={() => void toggle()}
            disabled={loading || !initialized}
            aria-label={
              codingMode
                ? t("codingMode.exitTooltip")
                : t("codingMode.enterTooltip")
            }
          >
            <span className="flex items-center">
              {codingMode ? <MessageSquare size={14} /> : <Code size={14} />}
            </span>
            <span className="leading-none">
              {codingMode ? t("codingMode.btnChat") : t("codingMode.btnCode")}
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          {codingMode
            ? t("codingMode.exitTooltip")
            : t("codingMode.enterTooltip")}
        </TooltipContent>
      </Tooltip>

      {/* Step 1: Experimental warning */}
      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent className="max-w-[440px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FlaskConical size={16} className="text-amber-500" />
              {t("codingMode.experimental")}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t("codingMode.experimentalDesc")}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2.5 py-1 pb-2">
            <p className="text-[14px] text-foreground/88 leading-relaxed m-0">
              {t("codingMode.experimentalDesc")}
            </p>
            <p className="text-[12px] text-foreground/45 bg-foreground/[0.04] border-l-[3px] border-amber-400 px-2.5 py-2 rounded-[0_4px_4px_0] leading-relaxed m-0">
              {t("codingMode.experimentalNote")}
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfirm(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={loading}
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {t("codingMode.confirmBtn")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Step 2: Project selection */}
      <ProjectSelectModal
        open={showProjectSelect}
        onClose={() => {
          setShowProjectSelect(false);
          void activate();
        }}
        onConfirm={() => void handleProjectConfirm()}
      />
    </>
  );
}
