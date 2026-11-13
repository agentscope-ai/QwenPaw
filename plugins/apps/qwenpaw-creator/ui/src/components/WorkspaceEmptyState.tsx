import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, FolderOpen, Layers3, Palette, Search } from "lucide-react";
import { useAgentWorkingState } from "@/selectors/agentWorkingSelectors";
import AgentActivityIndicator from "@/components/agent/AgentActivityIndicator";

type WorkspaceArea =
  | "blueprint"
  | "script"
  | "episodes"
  | "assets"
  | "visual"
  | "research";
const icons = {
  blueprint: BookOpen,
  script: BookOpen,
  episodes: Layers3,
  assets: FolderOpen,
  visual: Palette,
  research: Search,
};

/** Placeholder art is decorative: activity always comes from the runtime. */
export default function WorkspaceEmptyState({
  projectId,
  area,
  compact = false,
}: {
  projectId: string;
  area: WorkspaceArea;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const activity = useAgentWorkingState(projectId);
  const [longWait, setLongWait] = useState(false);
  useEffect(() => {
    setLongWait(false);
    if (!activity.working) return;
    const timer = window.setTimeout(() => setLongWait(true), 30_000);
    return () => window.clearTimeout(timer);
  }, [activity.working, projectId]);
  const Icon = icons[area];
  const animated = activity.working || activity.state === "loading";
  const hintKey =
    activity.state === "working"
      ? longWait
        ? "longWait"
        : "workingHint"
      : activity.state === "waiting"
      ? "waitingHint"
      : activity.state === "preparing"
      ? "preparingHint"
      : activity.state === "reconnecting"
      ? "reconnectingHint"
      : activity.state === "stopping"
      ? "stoppingHint"
      : activity.state === "stopped"
      ? "stoppedHint"
      : activity.state === "error"
      ? "errorHint"
      : activity.state === "loading"
      ? "loadingHint"
      : "idleHint";
  return (
    <div
      className="workspace-empty"
      data-workspace-empty={area}
      data-state={activity.state}
      data-compact={compact}
    >
      <div
        className={`workspace-empty-art ${animated ? "is-active" : ""}`}
        aria-hidden="true"
      >
        <div className="workspace-empty-paper">
          <span />
          <span />
          <span />
        </div>
        <span
          className={`workspace-empty-icon ${
            animated ? "agent-working-breathe" : ""
          }`}
        >
          <Icon />
        </span>
      </div>
      <div className="workspace-empty-copy">
        <p className="workspace-empty-eyebrow">{t(`workspaceEmpty.${area}`)}</p>
        <div
          className="workspace-empty-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {activity.state !== "idle" && (
            <AgentActivityIndicator phase={activity.indicatorPhase} />
          )}
          <h3>{activity.hint || t("workspaceEmpty.idleTitle")}</h3>
        </div>
        <p className="workspace-empty-description">
          {t(`workspaceEmpty.${hintKey}`)}
        </p>
      </div>
      {animated && (
        <div
          className="agent-working-shimmer workspace-empty-flow"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
