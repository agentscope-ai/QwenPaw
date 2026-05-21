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

import { useCallback, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { Badge, Tooltip } from "antd";
import {
  GitBranch,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  CheckSquare,
} from "lucide-react";
import FileTree from "./FileTree";
import TabbedEditor, { type EditorTab } from "./TabbedEditor";
import GitPanel from "./GitPanel";
import Chat from "../Chat";
import { useCodingMode, useCurrentTodos } from "../../stores/codingModeStore";
import styles from "./index.module.less";

type LeftPane = "files" | "git";

export default function CodingPage() {
  const { codingMode } = useCodingMode();
  const todos = useCurrentTodos();
  const pendingTodos = todos.filter(
    (t) => t.status !== "done" && t.status !== "cancelled",
  ).length;

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

  // ---- Editor tabs -------------------------------------------------------
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabPath, setActiveTabPath] = useState("");

  const handleFileSelect = useCallback((path: string, content: string) => {
    setTabs((prev) => {
      if (prev.find((t) => t.path === path)) return prev;
      return [...prev, { path, content, dirty: false }];
    });
    setActiveTabPath(path);
  }, []);

  const handleTabClose = useCallback(
    (path: string) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t.path !== path);
        if (activeTabPath === path) {
          const idx = prev.findIndex((t) => t.path === path);
          setActiveTabPath(next[idx]?.path ?? next[idx - 1]?.path ?? "");
        }
        return next;
      });
    },
    [activeTabPath],
  );

  const handleTabDirtyChange = useCallback((path: string, dirty: boolean) => {
    setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, dirty } : t)));
  }, []);

  const handleTabContentChange = useCallback(
    (path: string, content: string) => {
      setTabs((prev) =>
        prev.map((t) => (t.path === path ? { ...t, content } : t)),
      );
    },
    [],
  );

  if (!codingMode) {
    return (
      <div className={styles.disabled}>
        <p>Enable Coding Mode from the header to access the IDE layout.</p>
      </div>
    );
  }

  const dirtyCount = tabs.filter((t) => t.dirty).length;

  return (
    <div className={styles.root}>
      {/* ── Activity bar (left edge, icon-only like VS Code) ───────────── */}
      <div className={styles.activityBar}>
        <Tooltip title="Explorer" placement="right">
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
        </Tooltip>

        <Tooltip title="Source Control" placement="right">
          <button
            type="button"
            className={`${styles.actBtn} ${
              leftOpen && leftPane === "git" ? styles.actBtnActive : ""
            }`}
            onClick={() => toggleLeft("git")}
          >
            <GitBranch size={18} />
          </button>
        </Tooltip>

        <div className={styles.actBarSpacer} />

        {pendingTodos > 0 && (
          <Tooltip
            title={`${pendingTodos} tasks in progress`}
            placement="right"
          >
            <div className={styles.actBadge}>
              <CheckSquare size={16} />
              <span className={styles.actBadgeNum}>{pendingTodos}</span>
            </div>
          </Tooltip>
        )}
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
              onTabSelect={setActiveTabPath}
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
                  <Tooltip title="Hide chat panel">
                    <button
                      type="button"
                      className={styles.chatCloseBtn}
                      onClick={() => setRightOpen(false)}
                    >
                      <PanelRightClose size={13} />
                    </button>
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
          <Tooltip title="Show chat panel" placement="left">
            <button
              type="button"
              className={styles.chatReopenBtn}
              onClick={() => setRightOpen(true)}
            >
              <Badge count={dirtyCount} size="small">
                <PanelRightOpen size={16} />
              </Badge>
            </button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
