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
import { useAppMessage } from "../../hooks/useAppMessage";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  const { message } = useAppMessage();
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
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [showAllUnstaged, setShowAllUnstaged] = useState(false);
  const [showAllStaged, setShowAllStaged] = useState(false);
  const FILE_LIMIT = 50;
  const [activeTab, setActiveTab] = useState<"changes" | "log">("changes");

  const refresh = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([gitApi.status(), gitApi.branches()]);
      setStatus(s);
      setBranches(b);
    } catch {
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

  useEffect(() => {
    setStatus(null);
    setLog([]);
    void refresh();
    void refreshLog();
  }, [projectDir, refresh, refreshLog]);

  useEffect(() => {
    pollingRef.current = setInterval(() => void refresh(), 10000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [refresh]);

  const handleCheckout = useCallback(
    async (branch: string) => {
      try {
        await gitApi.checkout(branch);
        await refresh();
        message.success(`Switched to ${branch}`);
      } catch (e: unknown) {
        message.error(String(e));
      }
    },
    [refresh, message],
  );

  const handleCreateBranch = useCallback(async () => {
    if (!newBranchName.trim()) return;
    try {
      await gitApi.checkout(newBranchName.trim(), true);
      setNewBranchModal(false);
      setNewBranchName("");
      await refresh();
      message.success(`Created & switched to ${newBranchName.trim()}`);
    } catch (e: unknown) {
      message.error(String(e));
    }
  }, [newBranchName, refresh, message]);

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

  const handleDiscard = useCallback(
    async (file: GitChangedFile) => {
      try {
        await gitApi.discard([file.path]);
        await refresh();
        message.success(`Discarded changes in ${file.path}`);
      } catch (e: unknown) {
        message.error(String(e));
      }
    },
    [refresh, message],
  );

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

  const handleRevert = useCallback(
    async (commit: CommitInfo) => {
      try {
        await gitApi.revert(commit.hash);
        await refresh();
        await refreshLog();
        message.success(`Reverted commit ${commit.hash}`);
      } catch (e: unknown) {
        message.error(String(e));
      }
    },
    [refresh, refreshLog, message],
  );

  const handleCommit = useCallback(async () => {
    if (!commitMsg.trim()) {
      message.warning("Please enter a commit message");
      return;
    }
    const hasStaged = status?.changes.some((f) => f.staged);
    if (!hasStaged) {
      message.warning("No staged files. Stage changes before committing.");
      return;
    }
    setCommitting(true);
    try {
      await gitApi.commit(commitMsg.trim());
      setCommitMsg("");
      await refresh();
      await refreshLog();
      message.success("Committed successfully");
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : String(e);
      if (raw.includes("nothing to commit")) {
        message.warning("Nothing to commit");
      } else if (raw.includes("nothing added to commit")) {
        message.warning("No staged files. Stage changes before committing.");
      } else {
        message.error(raw);
      }
    } finally {
      setCommitting(false);
    }
  }, [commitMsg, status, refresh, refreshLog, message]);

  if (status === null) return null;

  const staged = status.changes.filter((f) => f.staged);
  const unstaged = status.changes.filter((f) => !f.staged);
  const localBranches = branches.filter((b) => !b.remote);

  const visibleStaged = showAllStaged ? staged : staged.slice(0, FILE_LIMIT);
  const visibleUnstaged = showAllUnstaged
    ? unstaged
    : unstaged.slice(0, FILE_LIMIT);

  return (
    <div className={styles.panel}>
      {/* Branch bar */}
      <div className={styles.branchBar}>
        <GitBranch size={13} className={styles.branchIcon} />
        <Select value={status.branch} onValueChange={handleCheckout}>
          <SelectTrigger className="h-6 text-xs flex-1 min-w-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {localBranches.map((b) => (
              <SelectItem key={b.name} value={b.name} className="text-xs">
                {b.name}
              </SelectItem>
            ))}
            <div
              className="flex items-center gap-1 px-2 py-1 text-xs cursor-pointer hover:bg-muted"
              onClick={() => setNewBranchModal(true)}
            >
              <Plus size={12} /> New branch
            </div>
          </SelectContent>
        </Select>
        {status.ahead > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-600">
            ↑{status.ahead}
          </span>
        )}
        {status.behind > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-orange-500/20 text-orange-600">
            ↓{status.behind}
          </span>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
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
          </TooltipTrigger>
          <TooltipContent>Refresh</TooltipContent>
        </Tooltip>
      </div>

      {/* Tabs */}
      <div className="flex border-b text-xs">
        <button
          className={`px-3 py-1.5 transition-colors ${
            activeTab === "changes"
              ? "border-b-2 border-primary font-medium"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setActiveTab("changes")}
        >
          Changes{" "}
          {status.changes.length > 0 && (
            <span className={styles.badge}>{status.changes.length}</span>
          )}
        </button>
        <button
          className={`px-3 py-1.5 transition-colors ${
            activeTab === "log"
              ? "border-b-2 border-primary font-medium"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setActiveTab("log")}
        >
          History
        </button>
      </div>

      {activeTab === "changes" && (
        <div className={styles.changesPane}>
          {staged.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>
                <span>Staged ({staged.length})</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className={styles.iconBtn}
                      onClick={() => void gitApi.unstage([]).then(refresh)}
                    >
                      <Minus size={11} />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>Unstage all</TooltipContent>
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

          {unstaged.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>
                <span>Changes ({unstaged.length})</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className={styles.iconBtn}
                      onClick={() => void handleStageAll()}
                    >
                      <Plus size={11} />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>Stage all</TooltipContent>
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
      )}

      {activeTab === "log" && (
        <div className={styles.logPane}>
          {log.length === 0 ? (
            <p className={styles.empty}>No commits yet</p>
          ) : (
            log.map((c) => (
              <CommitRow
                key={c.hash}
                commit={c}
                onDiff={() => void handleShowCommitDiff(c)}
                onRevert={() => void handleRevert(c)}
              />
            ))
          )}
        </div>
      )}

      {/* Commit box */}
      <div className={styles.commitBox}>
        <Textarea
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
          size="sm"
          className="w-full mt-1"
          disabled={committing}
          onClick={handleCommit}
        >
          <GitCommit size={12} className="mr-1" />
          {committing ? "Committing…" : "Commit"}
        </Button>
      </div>

      {/* Diff dialog */}
      <Dialog open={!!diffFile} onOpenChange={(o) => !o && setDiffFile(null)}>
        <DialogContent className="max-w-[80vw]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-1.5">
              <FileDiff size={14} />
              {diffFile?.title ?? diffFile?.path}
            </DialogTitle>
          </DialogHeader>
          <div className="overflow-auto max-h-[70vh]">
            {diffFile && <UnifiedDiffView diff={diffFile.diff} />}
          </div>
        </DialogContent>
      </Dialog>

      {/* New branch dialog */}
      <Dialog
        open={newBranchModal}
        onOpenChange={(o) => !o && setNewBranchModal(false)}
      >
        <DialogContent className="max-w-[360px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-1.5">
              <GitMerge size={14} />
              New branch
            </DialogTitle>
          </DialogHeader>
          <Input
            placeholder="branch-name"
            value={newBranchName}
            onChange={(e) => setNewBranchName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void handleCreateBranch()}
            autoFocus
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setNewBranchModal(false);
                setNewBranchName("");
              }}
            >
              Cancel
            </Button>
            <Button onClick={handleCreateBranch}>Create & Switch</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Commit row with revert confirm
// ---------------------------------------------------------------------------

interface CommitRowProps {
  commit: CommitInfo;
  onDiff: () => void;
  onRevert: () => void;
}

function CommitRow({ commit: c, onDiff, onRevert }: CommitRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  return (
    <div className={styles.logEntry}>
      <div className={styles.logEntryTop}>
        <span className={styles.logHash}>{c.hash}</span>
        <span className={styles.logMsg}>{c.message}</span>
        <div className={styles.logActions}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className={styles.iconBtn} onClick={onDiff}>
                <FileDiff size={11} />
              </button>
            </TooltipTrigger>
            <TooltipContent>View diff</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={styles.iconBtn}
                onClick={() => setConfirmOpen(true)}
              >
                <Undo2 size={11} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Revert this commit</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <span className={styles.logMeta}>
        {c.author} · {c.date}
      </span>

      <AlertDialog
        open={confirmOpen}
        onOpenChange={(o) => !o && setConfirmOpen(false)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{`Revert commit "${c.message}"?`}</AlertDialogTitle>
            <AlertDialogDescription>
              This creates a new commit that undoes these changes.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                onRevert();
                setConfirmOpen(false);
              }}
            >
              Revert
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  return (
    <div className={styles.fileRow}>
      <StatusBadge status={file.status} />
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={styles.fileName}>{name}</span>
        </TooltipTrigger>
        <TooltipContent>{file.path}</TooltipContent>
      </Tooltip>
      <div className={styles.fileActions}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" className={styles.iconBtn} onClick={onDiff}>
              <FileDiff size={11} />
            </button>
          </TooltipTrigger>
          <TooltipContent>View diff</TooltipContent>
        </Tooltip>
        {onDiscard && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className={styles.iconBtn}
                  onClick={() => setConfirmDiscard(true)}
                >
                  <RotateCcw size={11} />
                </button>
              </TooltipTrigger>
              <TooltipContent>Discard changes</TooltipContent>
            </Tooltip>
            <AlertDialog
              open={confirmDiscard}
              onOpenChange={(o) => !o && setConfirmDiscard(false)}
            >
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Discard changes?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {`Discard all changes in ${file.path}?`}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-destructive text-destructive-foreground"
                    onClick={() => {
                      onDiscard();
                      setConfirmDiscard(false);
                    }}
                  >
                    Discard
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" className={styles.iconBtn} onClick={onStage}>
              {actionIcon}
            </button>
          </TooltipTrigger>
          <TooltipContent>{actionTip}</TooltipContent>
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
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
