/**
 * GitPanel – Source Control panel for Coding Mode.
 *
 * Features:
 *   • Current branch + branch switcher (dropdown)
 *   • Changed-files list with stage/unstage checkboxes
 *   • Per-file diff viewer (unified diff text)
 *   • Commit message input + Commit button
 *   • Recent commits log
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  Input,
  message,
  Modal,
  Popconfirm,
  Select,
  Tabs,
  Tag,
  Tooltip,
} from "antd";
import {
  GitBranch,
  GitCommit,
  GitMerge,
  RefreshCw,
  Plus,
  Minus,
  FileDiff,
  RotateCcw,
  Undo2,
} from "lucide-react";
import { gitApi } from "../../api/modules/git";
import type {
  GitStatus,
  BranchInfo,
  CommitInfo,
  GitChangedFile,
} from "../../api/modules/git";
import { useProjectDir } from "../../stores/codingModeStore";
import styles from "./GitPanel.module.less";

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  M: { label: "M", color: "#f0ad4e" },
  A: { label: "A", color: "#5cb85c" },
  D: { label: "D", color: "#d9534f" },
  R: { label: "R", color: "#5bc0de" },
  "?": { label: "U", color: "#aaa" },
};

function StatusBadge({ status }: { status: string }) {
  const info = STATUS_LABELS[status] ?? { label: status, color: "#aaa" };
  return (
    <span className={styles.statusBadge} style={{ color: info.color }}>
      {info.label}
    </span>
  );
}

// ---------------------------------------------------------------------------

export default function GitPanel() {
  const { projectDir } = useProjectDir();
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [branches, setBranches] = useState<BranchInfo[]>([]);
  const [log, setLog] = useState<CommitInfo[]>([]);
  const [commitMsg, setCommitMsg] = useState("");
  const [committing, setCommitting] = useState(false);
  const [diffFile, setDiffFile] = useState<{
    path: string;
    staged: boolean;
    diff: string;
    title?: string;
  } | null>(null);
  const [newBranchModal, setNewBranchModal] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [msgApi, contextHolder] = message.useMessage();
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /** Show full list when > FILE_LIMIT items */
  const [showAllUnstaged, setShowAllUnstaged] = useState(false);
  const [showAllStaged, setShowAllStaged] = useState(false);
  const FILE_LIMIT = 50;

  const refresh = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([gitApi.status(), gitApi.branches()]);
      setStatus(s);
      setBranches(b);
    } catch {
      // Not a git repo or git not available – silently hide
      setStatus(null);
    }
  }, []);

  const refreshLog = useCallback(async () => {
    try {
      setLog(await gitApi.log(50));
    } catch {
      setLog([]);
    }
  }, []);

  // Re-fetch everything when the active coding project changes
  useEffect(() => {
    setStatus(null);
    setLog([]);
    void refresh();
    void refreshLog();
  }, [projectDir, refresh, refreshLog]);

  useEffect(() => {
    // Poll every 10 s — reduced from 5 s to cut API load
    pollingRef.current = setInterval(() => void refresh(), 10000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [refresh]);

  // ---- Branch actions -------------------------------------------------------

  const handleCheckout = useCallback(
    async (branch: string) => {
      try {
        await gitApi.checkout(branch);
        await refresh();
        void msgApi.success(`Switched to ${branch}`);
      } catch (e: unknown) {
        void msgApi.error(String(e));
      }
    },
    [refresh, msgApi],
  );

  const handleCreateBranch = useCallback(async () => {
    if (!newBranchName.trim()) return;
    try {
      await gitApi.checkout(newBranchName.trim(), true);
      setNewBranchModal(false);
      setNewBranchName("");
      await refresh();
      void msgApi.success(`Created & switched to ${newBranchName.trim()}`);
    } catch (e: unknown) {
      void msgApi.error(String(e));
    }
  }, [newBranchName, refresh, msgApi]);

  // ---- Stage / unstage ------------------------------------------------------

  const handleStage = useCallback(
    async (file: GitChangedFile) => {
      await gitApi.stage([file.path]);
      await refresh();
    },
    [refresh],
  );

  const handleUnstage = useCallback(
    async (file: GitChangedFile) => {
      await gitApi.unstage([file.path]);
      await refresh();
    },
    [refresh],
  );

  const handleStageAll = useCallback(async () => {
    await gitApi.stage([]);
    await refresh();
  }, [refresh]);

  // ---- Discard --------------------------------------------------------------

  const handleDiscard = useCallback(
    async (file: GitChangedFile) => {
      try {
        await gitApi.discard([file.path]);
        await refresh();
        void msgApi.success(`Discarded changes in ${file.path}`);
      } catch (e: unknown) {
        void msgApi.error(String(e));
      }
    },
    [refresh, msgApi],
  );

  // ---- Diff -----------------------------------------------------------------

  const handleShowDiff = useCallback(async (file: GitChangedFile) => {
    try {
      const isUntracked = file.status === "?";
      const res = await gitApi.diff(file.path, file.staged, isUntracked);
      setDiffFile({
        path: file.path,
        staged: file.staged,
        diff: res.diff,
        title: `${file.path}${file.staged ? " (staged)" : ""}`,
      });
    } catch {
      // ignore
    }
  }, []);

  const handleShowCommitDiff = useCallback(async (commit: CommitInfo) => {
    try {
      const res = await gitApi.commitDiff(commit.hash);
      setDiffFile({
        path: commit.hash,
        staged: false,
        diff: res.diff,
        title: `${commit.hash} · ${commit.message}`,
      });
    } catch {
      // ignore
    }
  }, []);

  // ---- Revert ---------------------------------------------------------------

  const handleRevert = useCallback(
    async (commit: CommitInfo) => {
      try {
        await gitApi.revert(commit.hash);
        await refresh();
        await refreshLog();
        void msgApi.success(`Reverted commit ${commit.hash}`);
      } catch (e: unknown) {
        void msgApi.error(String(e));
      }
    },
    [refresh, refreshLog, msgApi],
  );

  // ---- Commit ---------------------------------------------------------------

  const handleCommit = useCallback(async () => {
    if (!commitMsg.trim()) {
      void msgApi.warning("Please enter a commit message");
      return;
    }
    const hasStaged = status?.changes.some((f) => f.staged);
    if (!hasStaged) {
      void msgApi.warning("No staged files. Stage changes before committing.");
      return;
    }
    setCommitting(true);
    try {
      await gitApi.commit(commitMsg.trim());
      setCommitMsg("");
      await refresh();
      await refreshLog();
      void msgApi.success("Committed successfully");
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : String(e);
      if (raw.includes("nothing to commit")) {
        void msgApi.warning("Nothing to commit");
      } else if (raw.includes("nothing added to commit")) {
        void msgApi.warning(
          "No staged files. Stage changes before committing.",
        );
      } else {
        void msgApi.error(raw);
      }
    } finally {
      setCommitting(false);
    }
  }, [commitMsg, status, refresh, refreshLog, msgApi]);

  // ---- Render ---------------------------------------------------------------

  if (status === null) return null; // not a git repo

  const staged = status.changes.filter((f) => f.staged);
  const unstaged = status.changes.filter((f) => !f.staged);
  const localBranches = branches.filter((b) => !b.remote);

  const visibleStaged = showAllStaged ? staged : staged.slice(0, FILE_LIMIT);
  const visibleUnstaged = showAllUnstaged
    ? unstaged
    : unstaged.slice(0, FILE_LIMIT);

  return (
    <div className={styles.panel}>
      {contextHolder}

      {/* Branch bar */}
      <div className={styles.branchBar}>
        <GitBranch size={13} className={styles.branchIcon} />
        <Select
          size="small"
          className={styles.branchSelect}
          value={status.branch}
          onChange={handleCheckout}
          options={localBranches.map((b) => ({
            value: b.name,
            label: b.name,
          }))}
          popupRender={(menu) => (
            <>
              {menu}
              <div
                className={styles.newBranchOption}
                onClick={() => setNewBranchModal(true)}
              >
                <Plus size={12} /> New branch
              </div>
            </>
          )}
        />
        {status.ahead > 0 && (
          <Tag color="blue" className={styles.syncTag}>
            ↑{status.ahead}
          </Tag>
        )}
        {status.behind > 0 && (
          <Tag color="orange" className={styles.syncTag}>
            ↓{status.behind}
          </Tag>
        )}
        <Tooltip title="Refresh">
          <button
            type="button"
            className={styles.iconBtn}
            onClick={() => {
              setLoading(true);
              void refresh().finally(() => setLoading(false));
            }}
          >
            <RefreshCw size={12} className={loading ? styles.spinning : ""} />
          </button>
        </Tooltip>
      </div>

      <Tabs
        size="small"
        className={styles.tabs}
        items={[
          {
            key: "changes",
            label: (
              <span>
                Changes{" "}
                {status.changes.length > 0 && (
                  <span className={styles.badge}>{status.changes.length}</span>
                )}
              </span>
            ),
            children: (
              <div className={styles.changesPane}>
                {/* Staged */}
                {staged.length > 0 && (
                  <div className={styles.section}>
                    <div className={styles.sectionHeader}>
                      <span>Staged ({staged.length})</span>
                      <Tooltip title="Unstage all">
                        <button
                          type="button"
                          className={styles.iconBtn}
                          onClick={() => void gitApi.unstage([]).then(refresh)}
                        >
                          <Minus size={11} />
                        </button>
                      </Tooltip>
                    </div>
                    {visibleStaged.map((f) => (
                      <FileRow
                        key={f.path + "-staged"}
                        file={f}
                        onStage={() => void handleUnstage(f)}
                        onDiff={() => void handleShowDiff(f)}
                        actionIcon={<Minus size={11} />}
                        actionTip="Unstage"
                      />
                    ))}
                    {!showAllStaged && staged.length > FILE_LIMIT && (
                      <button
                        type="button"
                        className={styles.showMoreBtn}
                        onClick={() => setShowAllStaged(true)}
                      >
                        Show all {staged.length} files…
                      </button>
                    )}
                  </div>
                )}

                {/* Unstaged */}
                {unstaged.length > 0 && (
                  <div className={styles.section}>
                    <div className={styles.sectionHeader}>
                      <span>Changes ({unstaged.length})</span>
                      <Tooltip title="Stage all">
                        <button
                          type="button"
                          className={styles.iconBtn}
                          onClick={() => void handleStageAll()}
                        >
                          <Plus size={11} />
                        </button>
                      </Tooltip>
                    </div>
                    {visibleUnstaged.map((f) => (
                      <FileRow
                        key={f.path + "-unstaged"}
                        file={f}
                        onStage={() => void handleStage(f)}
                        onDiff={() => void handleShowDiff(f)}
                        onDiscard={() => void handleDiscard(f)}
                        actionIcon={<Plus size={11} />}
                        actionTip="Stage"
                      />
                    ))}
                    {!showAllUnstaged && unstaged.length > FILE_LIMIT && (
                      <button
                        type="button"
                        className={styles.showMoreBtn}
                        onClick={() => setShowAllUnstaged(true)}
                      >
                        Show all {unstaged.length} files…
                      </button>
                    )}
                  </div>
                )}

                {status.changes.length === 0 && (
                  <p className={styles.empty}>No changes</p>
                )}
              </div>
            ),
          },
          {
            key: "log",
            label: "History",
            children: (
              <div className={styles.logPane}>
                {log.length === 0 ? (
                  <p className={styles.empty}>No commits yet</p>
                ) : (
                  log.map((c) => (
                    <div key={c.hash} className={styles.logEntry}>
                      <div className={styles.logEntryTop}>
                        <span className={styles.logHash}>{c.hash}</span>
                        <span className={styles.logMsg}>{c.message}</span>
                        <div className={styles.logActions}>
                          <Tooltip title="View diff">
                            <button
                              type="button"
                              className={styles.iconBtn}
                              onClick={() => void handleShowCommitDiff(c)}
                            >
                              <FileDiff size={11} />
                            </button>
                          </Tooltip>
                          <Popconfirm
                            title={`Revert commit "${c.message}"?`}
                            description="This creates a new commit that undoes these changes."
                            onConfirm={() => void handleRevert(c)}
                            okText="Revert"
                            cancelText="Cancel"
                            placement="topRight"
                          >
                            <Tooltip title="Revert this commit">
                              <button type="button" className={styles.iconBtn}>
                                <Undo2 size={11} />
                              </button>
                            </Tooltip>
                          </Popconfirm>
                        </div>
                      </div>
                      <span className={styles.logMeta}>
                        {c.author} · {c.date}
                      </span>
                    </div>
                  ))
                )}
              </div>
            ),
          },
        ]}
      />

      {/* Commit box — outside Tabs so it's always pinned at bottom */}
      <div className={styles.commitBox}>
        <Input.TextArea
          rows={2}
          placeholder="Commit message…"
          value={commitMsg}
          onChange={(e) => setCommitMsg(e.target.value)}
          className={styles.commitInput}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              void handleCommit();
            }
          }}
        />
        <Button
          type="primary"
          size="small"
          block
          loading={committing}
          onClick={handleCommit}
          icon={<GitCommit size={12} />}
        >
          Commit
        </Button>
      </div>

      {/* Diff modal */}
      <Modal
        open={!!diffFile}
        title={
          <span>
            <FileDiff size={14} style={{ marginRight: 6 }} />
            {diffFile?.title ?? diffFile?.path}
          </span>
        }
        onCancel={() => setDiffFile(null)}
        footer={null}
        width="80vw"
        styles={{ body: { padding: 0 } }}
      >
        {diffFile && <UnifiedDiffView diff={diffFile.diff} />}
      </Modal>

      {/* New branch modal */}
      <Modal
        open={newBranchModal}
        title={
          <span>
            <GitMerge size={14} style={{ marginRight: 6 }} />
            New branch
          </span>
        }
        onOk={handleCreateBranch}
        onCancel={() => {
          setNewBranchModal(false);
          setNewBranchName("");
        }}
        okText="Create & Switch"
        width={360}
      >
        <Input
          placeholder="branch-name"
          value={newBranchName}
          onChange={(e) => setNewBranchName(e.target.value)}
          onPressEnter={handleCreateBranch}
          autoFocus
        />
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// File row
// ---------------------------------------------------------------------------

interface FileRowProps {
  file: GitChangedFile;
  onStage: () => void;
  onDiff: () => void;
  onDiscard?: () => void;
  actionIcon: React.ReactNode;
  actionTip: string;
}

function FileRow({
  file,
  onStage,
  onDiff,
  onDiscard,
  actionIcon,
  actionTip,
}: FileRowProps) {
  const name = file.path.split("/").pop() ?? file.path;
  return (
    <div className={styles.fileRow}>
      <StatusBadge status={file.status} />
      <Tooltip title={file.path}>
        <span className={styles.fileName}>{name}</span>
      </Tooltip>
      <div className={styles.fileActions}>
        <Tooltip title="View diff">
          <button type="button" className={styles.iconBtn} onClick={onDiff}>
            <FileDiff size={11} />
          </button>
        </Tooltip>
        {onDiscard && (
          <Popconfirm
            title="Discard changes?"
            description={`Discard all changes in ${file.path}?`}
            onConfirm={onDiscard}
            okText="Discard"
            cancelText="Cancel"
            okButtonProps={{ danger: true }}
            placement="topRight"
          >
            <Tooltip title="Discard changes">
              <button type="button" className={styles.iconBtn}>
                <RotateCcw size={11} />
              </button>
            </Tooltip>
          </Popconfirm>
        )}
        <Tooltip title={actionTip}>
          <button type="button" className={styles.iconBtn} onClick={onStage}>
            {actionIcon}
          </button>
        </Tooltip>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unified diff viewer
// ---------------------------------------------------------------------------

function UnifiedDiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <div className={styles.diffEmpty}>No diff available.</div>;
  }
  const lines = diff.split("\n");
  return (
    <pre className={styles.diffViewer}>
      {lines.map((line, i) => {
        let cls = styles.diffCtx;
        if (line.startsWith("+++") || line.startsWith("---")) {
          cls = styles.diffMeta;
        } else if (line.startsWith("@@")) {
          cls = styles.diffHunk;
        } else if (line.startsWith("+")) {
          cls = styles.diffAdd;
        } else if (line.startsWith("-")) {
          cls = styles.diffDel;
        } else if (line.startsWith("diff ") || line.startsWith("index ")) {
          cls = styles.diffMeta;
        }
        return (
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
