/**
 * Coding Mode – VS Code-like three-column layout.
 *
 *   ┌─────────────┬──────────────────────────┬──────────────┐
 *   │  File Tree  │     TabbedEditor          │    Chat      │
 *   │  (Explorer) │    (primary workspace)    │  (AI panel)  │
 *   └─────────────┴──────────────────────────┴──────────────┘
 *
 * Each column is resizable via react-resizable-panels.
 * File tree and Chat can each be toggled from the activity bar.
 */

import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Group, Panel, Separator } from "react-resizable-panels";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  GitBranch,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import FileTree from "./FileTree";
import TabbedEditor from "./TabbedEditor";
import GitPanel from "./GitPanel";
import Chat from "../Chat";
import { useCodingMode } from "../../stores/codingModeStore";
import {
  useCurrentTabs,
  useCurrentActiveTabPath,
  useCodingTabsStore,
} from "../../stores/codingTabsStore";
import { useAgentStore } from "../../stores/agentStore";
import { workspaceApi } from "../../api/modules/workspace";
import styles from "./index.module.less";

type LeftPane = "files" | "git";

export default function CodingPage() {
  const { codingMode, initialized } = useCodingMode();

  // ---- Panel visibility --------------------------------------------------
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [leftPane, setLeftPane] = useState<LeftPane>("files");

  const toggleLeft = useCallback(
    (pane: LeftPane) => {
      setLeftPane(pane);
      setLeftOpen((cur) => (cur && leftPane === pane ? false : true));
    },
    [leftPane],
  );

  // ---- Editor tabs (per-agent, persisted) --------------------------------
  const { selectedAgent } = useAgentStore();
  const tabs = useCurrentTabs();
  const activeTabPath = useCurrentActiveTabPath();
  const { openTab, closeTab, setActiveTab, setTabContent, setTabDirty } =
    useCodingTabsStore();

  // Hydrate persisted tab contents (path-list survives reload but content
  // doesn't — re-fetch from disk via the cached loadCodeFile). Drop tabs
  // whose file no longer exists on disk.
  useEffect(() => {
    let cancelled = false;
    const toHydrate = tabs.filter((t) => t.content === "");
    if (toHydrate.length === 0) return undefined;

    void Promise.all(
      toHydrate.map(async (t) => {
        try {
          const result = await workspaceApi.loadCodeFile(t.path);
          return { path: t.path, content: result.content ?? "", ok: true };
        } catch {
          return { path: t.path, content: "", ok: false };
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      for (const r of results) {
        if (r.ok) {
          setTabContent(selectedAgent, r.path, r.content);
        } else {
          closeTab(selectedAgent, r.path);
        }
      }
    });

    return () => {
      cancelled = true;
    };
    // Re-run on agent switch; ignore tabs/setters churn — the content==""
    // filter naturally short-circuits when nothing needs hydration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  const handleFileSelect = useCallback(
    (path: string, content: string) => {
      openTab(selectedAgent, { path, content, dirty: false });
      setActiveTab(selectedAgent, path);
    },
    [selectedAgent, openTab, setActiveTab],
  );

  const handleTabSelect = useCallback(
    (path: string) => setActiveTab(selectedAgent, path),
    [selectedAgent, setActiveTab],
  );

  const handleTabClose = useCallback(
    (path: string) => {
      const idx = tabs.findIndex((t) => t.path === path);
      closeTab(selectedAgent, path);
      if (activeTabPath === path) {
        const fallback = tabs[idx + 1]?.path ?? tabs[idx - 1]?.path ?? "";
        setActiveTab(selectedAgent, fallback);
      }
    },
    [tabs, activeTabPath, selectedAgent, closeTab, setActiveTab],
  );

  const handleTabDirtyChange = useCallback(
    (path: string, dirty: boolean) => setTabDirty(selectedAgent, path, dirty),
    [selectedAgent, setTabDirty],
  );

  const handleTabContentChange = useCallback(
    (path: string, content: string) =>
      setTabContent(selectedAgent, path, content),
    [selectedAgent, setTabContent],
  );

  if (initialized && !codingMode) {
    return <Navigate to="/chat" replace />;
  }

  const dirtyCount = tabs.filter((t) => t.dirty).length;

  return (
    <div className={styles.root}>
      {/* ── Activity bar (left edge, icon-only like VS Code) ───────────── */}
      <div className={styles.activityBar}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className={`${styles.actBtn} ${
                leftOpen && leftPane === "files" ? styles.actBtnActive : ""
              }`}
              onClick={() => toggleLeft("files")}
            >
              {leftOpen && leftPane === "files" ? (
                <PanelLeftClose size={18} />
              ) : (
                <PanelLeftOpen size={18} />
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Explorer</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className={`${styles.actBtn} ${
                leftOpen && leftPane === "git" ? styles.actBtnActive : ""
              }`}
              onClick={() => toggleLeft("git")}
            >
              <GitBranch size={18} />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Source Control</TooltipContent>
        </Tooltip>

        <div className={styles.actBarSpacer} />
      </div>

      {/* ── Three-column resizable layout ──────────────────────────────── */}
      <div className={styles.workspace}>
        <Group orientation="horizontal" className={styles.group}>
          {/* LEFT: Explorer / Git */}
          {leftOpen && (
            <>
              <Panel id="left" defaultSize="15%" className={styles.leftPanel}>
                {leftPane === "files" && (
                  <FileTree onFileSelect={handleFileSelect} />
                )}
                {leftPane === "git" && <GitPanel />}
              </Panel>
              <Separator className={styles.sep} />
            </>
          )}

          {/* CENTER: Editor (takes remaining space) */}
          <Panel
            id="center"
            defaultSize={
              leftOpen && rightOpen
                ? "55%"
                : leftOpen || rightOpen
                ? "70%"
                : "100%"
            }
          >
            <TabbedEditor
              tabs={tabs}
              activeTabPath={activeTabPath}
              onTabSelect={handleTabSelect}
              onTabClose={handleTabClose}
              onTabDirtyChange={handleTabDirtyChange}
              onTabContentChange={handleTabContentChange}
            />
          </Panel>

          {/* RIGHT: Chat */}
          {rightOpen && (
            <>
              <Separator className={styles.sep} />
              <Panel id="right" defaultSize="30%" className={styles.rightPanel}>
                <div className={styles.chatHeader}>
                  <span className={styles.chatTitle}>
                    <MessageSquare size={13} style={{ marginRight: 5 }} />
                    Chat
                  </span>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className={styles.chatCloseBtn}
                        onClick={() => setRightOpen(false)}
                      >
                        <PanelRightClose size={13} />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Hide chat panel</TooltipContent>
                  </Tooltip>
                </div>
                <div className={styles.chatBody}>
                  <Chat />
                </div>
              </Panel>
            </>
          )}
        </Group>

        {/* Chat re-open button when hidden */}
        {!rightOpen && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={styles.chatReopenBtn}
                onClick={() => setRightOpen(true)}
              >
                <span className="relative inline-flex">
                  <PanelRightOpen size={16} />
                  {dirtyCount > 0 && (
                    <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-0.5 text-[10px] flex items-center justify-center rounded-full bg-primary text-primary-foreground font-semibold">
                      {dirtyCount}
                    </span>
                  )}
                </span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="left">Show chat panel</TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
