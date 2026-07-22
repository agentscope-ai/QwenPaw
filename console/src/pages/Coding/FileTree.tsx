import { useCallback, useEffect, useMemo, useState } from "react";
import { Spin, Tooltip } from "antd";
import {
  FolderOpen,
  Folder,
  FileCode,
  FileText,
  File,
  RefreshCw,
  Settings2,
} from "lucide-react";
import { workspaceApi } from "../../api/modules/workspace";
import { gitApi } from "../../api/modules/git";
import { codingProjectApi } from "../../api/modules/codingProject";
import { useWorkspaceWatch } from "../../hooks/useWorkspaceWatch";
import { useProjectDir } from "../../stores/codingModeStore";
import { useCodeFileCacheStore } from "../../stores/codeFileCacheStore";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import { useAgentStore } from "../../stores/agentStore";
import ProjectSelectModal from "../../components/ProjectSelectModal";
import type { MdFileInfo } from "../../api/types";
import styles from "./FileTree.module.less";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TreeNode {
  name: string;
  path: string;
  type: "file" | "dir";
  children?: TreeNode[];
}

/** Simplified git decoration for a path */
type GitStatus = "modified" | "added" | "deleted" | "untracked";

/** Map of relative file path → git status */
type GitStatusMap = Map<string, GitStatus>;

// ---------------------------------------------------------------------------
// Tree builder
// ---------------------------------------------------------------------------

function buildTree(files: MdFileInfo[]): TreeNode[] {
  const nodeByPath = new Map<string, TreeNode>();
  const roots: TreeNode[] = [];

  for (const f of files) {
    const parts = f.filename.split("/");
    for (let i = 0; i < parts.length; i++) {
      const path = parts.slice(0, i + 1).join("/");
      if (nodeByPath.has(path)) continue;

      const isFile = i === parts.length - 1;
      const node: TreeNode = {
        name: parts[i],
        path,
        type: isFile ? "file" : "dir",
        children: isFile ? undefined : [],
      };
      nodeByPath.set(path, node);

      if (i === 0) {
        roots.push(node);
      } else {
        const parentPath = parts.slice(0, i).join("/");
        nodeByPath.get(parentPath)?.children?.push(node);
      }
    }
  }

  function sort(nodes: TreeNode[]): TreeNode[] {
    return nodes
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
        return a.name.localeCompare(b.name);
      })
      .map((n) => ({
        ...n,
        children: n.children ? sort(n.children) : undefined,
      }));
  }
  return sort(roots);
}

/** Build a set of directory paths that contain any changed files (for bubble-up). */
function buildDirStatusMap(statusMap: GitStatusMap): Map<string, GitStatus> {
  const dirMap = new Map<string, GitStatus>();

  const priority: Record<GitStatus, number> = {
    deleted: 3,
    modified: 2,
    added: 1,
    untracked: 0,
  };

  const set = (dirPath: string, s: GitStatus) => {
    const existing = dirMap.get(dirPath);
    if (!existing || priority[s] > priority[existing]) {
      dirMap.set(dirPath, s);
    }
  };

  for (const [filePath, status] of statusMap) {
    const parts = filePath.split("/");
    for (let i = 1; i < parts.length; i++) {
      set(parts.slice(0, i).join("/"), status);
    }
  }
  return dirMap;
}

// ---------------------------------------------------------------------------
// Git status helpers
// ---------------------------------------------------------------------------

function parseGitStatus(raw: string): GitStatus {
  const s = raw.trim().toUpperCase();
  if (s === "D") return "deleted";
  // "??" from git porcelain, "?" from backend normalization — both mean untracked
  if (s === "?" || s === "??") return "untracked";
  if (s === "A") return "added";
  return "modified";
}

// ---------------------------------------------------------------------------
// File icon
// ---------------------------------------------------------------------------

function getFileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const codeExts = new Set([
    "py",
    "ts",
    "tsx",
    "js",
    "jsx",
    "json",
    "yaml",
    "yml",
    "sh",
    "bash",
    "rs",
    "go",
    "cpp",
    "c",
    "h",
    "java",
    "kt",
    "swift",
    "rb",
    "php",
    "html",
    "css",
    "less",
    "scss",
    "sql",
    "toml",
    "ini",
    "env",
  ]);
  const textExts = new Set(["md", "txt", "rst", "log"]);
  if (codeExts.has(ext)) return <FileCode size={13} />;
  if (textExts.has(ext)) return <FileText size={13} />;
  return <File size={13} />;
}

// ---------------------------------------------------------------------------
// Git status badge (single letter like VS Code)
// ---------------------------------------------------------------------------

function GitBadge({ status }: { status: GitStatus }) {
  const label =
    status === "modified"
      ? "M"
      : status === "added"
      ? "A"
      : status === "deleted"
      ? "D"
      : "U";
  return (
    <span className={`${styles.gitBadge} ${styles[`git_${status}`]}`}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// NodeItem
// ---------------------------------------------------------------------------

interface NodeItemProps {
  node: TreeNode;
  depth: number;
  selectedPath: string;
  gitMap: GitStatusMap;
  dirMap: Map<string, GitStatus>;
  onSelect: (path: string) => void;
}

function NodeItem({
  node,
  depth,
  selectedPath,
  gitMap,
  dirMap,
  onSelect,
}: NodeItemProps) {
  const [expanded, setExpanded] = useState(false);
  const isSelected = selectedPath === node.path;

  if (node.type === "dir") {
    const dirStatus = dirMap.get(node.path);
    return (
      <>
        <div
          className={`${styles.node} ${
            dirStatus ? styles[`node_${dirStatus}`] : ""
          }`}
          style={{ paddingLeft: depth * 14 + 8 }}
          onClick={() => setExpanded((v) => !v)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && setExpanded((v) => !v)}
        >
          <span className={styles.nodeIcon}>
            {expanded ? (
              <FolderOpen size={13} className={styles.folderIcon} />
            ) : (
              <Folder size={13} className={styles.folderIcon} />
            )}
          </span>
          <span className={styles.nodeName}>{node.name}</span>
          {dirStatus && <GitBadge status={dirStatus} />}
        </div>
        {expanded &&
          node.children?.map((child) => (
            <NodeItem
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              gitMap={gitMap}
              dirMap={dirMap}
              onSelect={onSelect}
            />
          ))}
      </>
    );
  }

  const fileStatus = gitMap.get(node.path);
  return (
    <div
      className={`${styles.node} ${isSelected ? styles.selected : ""} ${
        fileStatus ? styles[`node_${fileStatus}`] : ""
      }`}
      style={{ paddingLeft: depth * 14 + 8 }}
      onClick={() => onSelect(node.path)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onSelect(node.path)}
    >
      <span className={`${styles.nodeIcon} ${styles.fileIcon}`}>
        {getFileIcon(node.name)}
      </span>
      <span
        className={`${styles.nodeName} ${
          fileStatus === "deleted" ? styles.deletedName : ""
        }`}
      >
        {node.name}
      </span>
      {fileStatus && <GitBadge status={fileStatus} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FileTree
// ---------------------------------------------------------------------------

interface FileTreeProps {
  onFileSelect: (path: string, content: string) => void;
}

export default function FileTree({ onFileSelect }: FileTreeProps) {
  const [nodes, setNodes] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState("");
  const [gitStatusMap, setGitStatusMap] = useState<GitStatusMap>(new Map());
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [projectName, setProjectName] = useState<string>("workspace");

  const { projectDir, setProjectDir } = useProjectDir();

  // Sync displayed project name from server; cancel stale in-flight requests
  useEffect(() => {
    let cancelled = false;
    codingProjectApi
      .get()
      .then((info) => {
        if (cancelled) return;
        setProjectName(info.name);
        if (projectDir === undefined && !info.is_workspace_default) {
          setProjectDir(info.path);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectDir]);

  const loadGitStatus = useCallback(async () => {
    try {
      const result = await gitApi.status();
      const map = new Map<string, GitStatus>();
      for (const f of result.changes ?? []) {
        map.set(f.path, parseGitStatus(f.status));
      }
      setGitStatusMap(map);
    } catch {
      // Non-git workspace — silently ignore
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [files] = await Promise.all([
        workspaceApi.listCodeFiles(),
        loadGitStatus(),
      ]);
      setNodes(buildTree(files));
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [loadGitStatus]);

  // Reload file tree when project switches (projectDir from store).
  // The cached file contents belong to the previous project root and would
  // be returned for matching paths in the new project — wipe them.
  useEffect(() => {
    useCodeFileCacheStore.getState().clear();
    void load();
  }, [load, projectDir]);

  // SSE handler: split by event type so saving an open file doesn't trigger
  // a full tree rescan, and so we drop stale entries from the file content
  // cache before the user opens the changed file again.
  useWorkspaceWatch((events) => {
    const cache = useCodeFileCacheStore.getState();
    let hasStructural = false;
    let hasModified = false;
    for (const e of events) {
      if (e.change === "added" || e.change === "deleted") {
        hasStructural = true;
        cache.invalidate(e.path);
      } else if (e.change === "modified") {
        hasModified = true;
        cache.invalidate(e.path);
      }
    }
    if (hasStructural) {
      void load();
    } else if (hasModified) {
      // Tree shape unchanged; only git decoration could have changed.
      void loadGitStatus();
    }
  });

  const dirStatusMap = useMemo(
    () => buildDirStatusMap(gitStatusMap),
    [gitStatusMap],
  );

  const handleSelect = useCallback(
    async (path: string) => {
      setSelectedPath(path);
      try {
        const result = await workspaceApi.loadCodeFile(path);
        onFileSelect(path, result.content ?? "");
      } catch (err: unknown) {
        const status =
          err instanceof Error && "status" in err
            ? (err as { status?: number }).status
            : undefined;
        // HTTP 413 = file too large; show a placeholder instead of blank tab
        const placeholder =
          status === 413
            ? "// File too large to open in the editor (> 5 MB)"
            : "";
        onFileSelect(path, placeholder);
      }
    },
    [onFileSelect],
  );

  const { selectedAgent } = useAgentStore();
  const { clearAgent } = useCodingTabsStore();

  const handleProjectConfirm = (_path: string | null) => {
    setProjectModalOpen(false);
    // Clear editor tabs from the previous project so stale files don't linger
    clearAgent(selectedAgent);
    // Reload file tree for the new project
    void load();
  };

  return (
    <div className={styles.tree}>
      {/* Project Picker (compact header bar) */}
      <div className={styles.projectBar}>
        <span
          className={styles.projectName}
          title={projectDir ?? "default workspace"}
        >
          {projectName}
        </span>
        <Tooltip title="Switch Project">
          <button
            type="button"
            className={styles.projectSwitchBtn}
            onClick={() => setProjectModalOpen(true)}
          >
            <Settings2 size={12} />
          </button>
        </Tooltip>
      </div>

      <div className={styles.treeHeader}>
        <span className={styles.treeTitle}>Files</span>
        <Tooltip title="Refresh">
          <button
            type="button"
            className={styles.refreshBtn}
            onClick={load}
            disabled={loading}
          >
            <RefreshCw size={12} className={loading ? styles.spinning : ""} />
          </button>
        </Tooltip>
      </div>
      {loading && nodes.length === 0 ? (
        <Spin size="small" className={styles.spin} />
      ) : (
        <div className={styles.nodeList}>
          {nodes.map((node) => (
            <NodeItem
              key={node.path}
              node={node}
              depth={0}
              selectedPath={selectedPath}
              gitMap={gitStatusMap}
              dirMap={dirStatusMap}
              onSelect={handleSelect}
            />
          ))}
        </div>
      )}

      <ProjectSelectModal
        open={projectModalOpen}
        onClose={() => setProjectModalOpen(false)}
        onConfirm={handleProjectConfirm}
      />
    </div>
  );
}
