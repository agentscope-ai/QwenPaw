import { useTranslation } from "react-i18next";
import { AgentDock } from "@/components/agent";
import EpisodeListPanel from "@/components/blueprint/EpisodeListPanel";
import {
  useAgentDockUiStore,
  type WorkspaceSidebarTab,
} from "@/store/agentDockUiStore";

/**
 * Left workspace sidebar (design 83:13383): a "创作助手 / 剧集列表" tab bar on top
 * of the AgentDock. The assistant tab shows the dock's conversation feed;
 * the episodes tab swaps the feed for the episode list while the composer
 * stays pinned at the bottom in both tabs. The active tab lives in the dock
 * UI store so a user's choice survives page navigation (blueprint ↔ plan).
 */
export default function WorkspaceSidebar() {
  const { t } = useTranslation();
  const tab = useAgentDockUiStore((state) => state.sidebarTab);
  const setTab = useAgentDockUiStore((state) => state.setSidebarTab);

  const tabs: { key: WorkspaceSidebarTab; label: string }[] = [
    { key: "assistant", label: t("sidebar.assistant") },
    { key: "episodes", label: t("sidebar.episodes") },
  ];

  const headerTabs = (
    <div
      data-workspace-sidebar-tabs
      className="flex min-w-0 items-center gap-6"
    >
      {tabs.map((item) => {
        const active = item.key === tab;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            data-active={active}
            className={`relative pb-1 text-sm transition-colors ${
              active
                ? "font-semibold text-[var(--color-text-primary)]"
                : "font-medium text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
            }`}
          >
            {item.label}
            {active && (
              <span className="absolute inset-x-0 -bottom-0.5 mx-auto h-0.5 w-6 rounded-full bg-[var(--color-text-primary)]" />
            )}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="flex min-h-0 shrink-0">
      <AgentDock
        sidebar
        anchor="left"
        headerSlot={headerTabs}
        feedSlot={tab === "episodes" ? <EpisodeListPanel /> : undefined}
      />
    </div>
  );
}
