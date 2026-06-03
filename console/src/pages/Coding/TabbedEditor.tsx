/**
 * TabbedEditor – multi-file Monaco editor with:
 *   • File tabs (close, dirty indicator, pending-diff indicator)
 *   • Monaco model-per-path (undo history & cursor persist on tab switch)
 *   • Inline Diff view when Agent modifies the open file:
 *       - Switches to DiffEditor (renderSideBySide: false → VS Code inline style)
 *       - Per-hunk "Keep"/"Undo" widgets + global "Keep all"/"Undo all"
 *   • Preview mode for images, Markdown, PDF, CSV (toggle per tab)
 *   • Toolbar "Copy to Chat" button injects `path:line[-line]` context
 *     into the Chat composer (raw Cmd/Ctrl+C still copies plain text)
 *   • Cmd/Ctrl+S to save
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Editor, {
  DiffEditor,
  type Monaco,
  type DiffOnMount,
} from "@monaco-editor/react";
import type { editor as MonacoEditor } from "monaco-editor";
import {
  Check,
  Code2,
  Eye,
  FileCode,
  GitCompareArrows,
  MessageSquarePlus,
  RotateCcw,
  Save,
  X,
} from "lucide-react";
import { Tooltip } from "antd";
import FilePreview, { isPreviewable } from "./FilePreview";
import { workspaceApi } from "../../api/modules/workspace";
import { useWorkspaceWatch } from "../../hooks/useWorkspaceWatch";
import { useTheme } from "../../contexts/ThemeContext";
import { setTextareaValue } from "../Chat/utils";
import { clearLastEditorCopy, setLastEditorCopy } from "./lastEditorCopy";
import {
  useCurrentDiffs,
  useCodingTabsStore,
  type EditorTab,
} from "../../stores/codingTabsStore";
import { useAgentStore } from "../../stores/agentStore";
import styles from "./TabbedEditor.module.less";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type { EditorTab };

interface TabbedEditorProps {
  tabs: EditorTab[];
  activeTabPath: string;
  onTabSelect: (path: string) => void;
  onTabClose: (path: string) => void;
  onTabDirtyChange: (path: string, dirty: boolean) => void;
  onTabContentChange: (path: string, content: string) => void;
  onFileSaved?: (path: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    sh: "shell",
    bash: "shell",
    html: "html",
    css: "css",
    less: "less",
    scss: "scss",
    sql: "sql",
    toml: "ini",
    rs: "rust",
    go: "go",
    java: "java",
    cpp: "cpp",
    c: "c",
    h: "c",
    kt: "kotlin",
    rb: "ruby",
  };
  return map[ext] ?? "plaintext";
}

function appendToChat(text: string): void {
  const senderEl = document.querySelector('[class*="sender"]');
  const textarea = senderEl?.querySelector(
    "textarea",
  ) as HTMLTextAreaElement | null;
  if (!textarea) return;
  const prev = textarea.value;
  setTextareaValue(textarea, prev ? `${prev}\n${text}` : text);
  textarea.focus();
}

type CopyMode = "whole-file" | "lines-only" | "with-code";

const stripTrailingNewlines = (s: string) => s.replace(/\n+$/, "");

// Classify a Monaco selection into one of three copy modes:
//   • whole-file  → output just the path (file contents fully covered)
//   • lines-only  → output `path:x-y` (selection spans complete lines)
//   • with-code   → output `path:x-y` + fenced code block (column-level partial)
// Geometric quirk handled: a triple-click style selection ending at column 1
// of the next line is normalised so the displayed end line is the previous one.
function detectCopyMode(
  selection: {
    startLineNumber: number;
    startColumn: number;
    endLineNumber: number;
    endColumn: number;
  },
  model: MonacoEditor.ITextModel,
): {
  mode: CopyMode;
  code: string;
  startLine: number;
  endLine: number;
} {
  const code = model.getValueInRange(selection);
  const startLine = selection.startLineNumber;
  let endLine = selection.endLineNumber;
  if (endLine > startLine && selection.endColumn === 1) {
    endLine -= 1;
  }

  if (stripTrailingNewlines(code) === stripTrailingNewlines(model.getValue())) {
    return { mode: "whole-file", code, startLine, endLine };
  }

  const lines: string[] = [];
  for (let l = startLine; l <= endLine; l += 1) {
    lines.push(model.getLineContent(l));
  }
  if (stripTrailingNewlines(code) === lines.join("\n")) {
    return { mode: "lines-only", code, startLine, endLine };
  }

  return { mode: "with-code", code, startLine, endLine };
}

function formatSelectionForChat(
  filePath: string,
  code: string,
  startLine: number,
  endLine: number,
  mode: CopyMode,
): string {
  if (mode === "whole-file") {
    return filePath;
  }
  const lineRange =
    startLine === endLine ? `${startLine}` : `${startLine}-${endLine}`;
  if (mode === "lines-only") {
    return `${filePath}:${lineRange}`;
  }
  const lang = getLanguage(filePath);
  return `${filePath}:${lineRange}\n\`\`\`${lang}\n${code}\n\`\`\``;
}

// ---------------------------------------------------------------------------
// Hunk-level Keep / Undo helpers
// ---------------------------------------------------------------------------

interface Hunk {
  originalStartLineNumber: number;
  originalEndLineNumber: number;
  modifiedStartLineNumber: number;
  modifiedEndLineNumber: number;
}

// Convert Monaco's 1-indexed inclusive [startLine..endLine] range to a
// 0-indexed [start, end) slice range. When endLine === 0 (or below
// startLine) the change is a pure insert with no source-side lines, so
// the range collapses to an empty slice at the insertion point.
function rangeFromLines(
  startLine: number,
  endLine: number,
): { start: number; end: number } {
  if (endLine === 0 || endLine < startLine) {
    return { start: startLine, end: startLine };
  }
  return { start: startLine - 1, end: endLine };
}

// Bake a hunk's modified content into the original baseline. The returned
// string is the new `original` for the pending diff; the kept block
// becomes equal on both sides and stops being a hunk, while other hunks
// remain visible.
function applyKeepHunk(original: string, modified: string, hunk: Hunk): string {
  const origLines = original.split("\n");
  const modLines = modified.split("\n");
  const o = rangeFromLines(
    hunk.originalStartLineNumber,
    hunk.originalEndLineNumber,
  );
  const m = rangeFromLines(
    hunk.modifiedStartLineNumber,
    hunk.modifiedEndLineNumber,
  );
  const replacement = modLines.slice(m.start, m.end);
  return [
    ...origLines.slice(0, o.start),
    ...replacement,
    ...origLines.slice(o.end),
  ].join("\n");
}

// Revert a hunk's modified content back to the original. The returned
// string is the new `modified` (which the caller should also write back
// to disk so the on-disk file matches the visible state).
function applyUndoHunk(original: string, modified: string, hunk: Hunk): string {
  const origLines = original.split("\n");
  const modLines = modified.split("\n");
  const o = rangeFromLines(
    hunk.originalStartLineNumber,
    hunk.originalEndLineNumber,
  );
  const m = rangeFromLines(
    hunk.modifiedStartLineNumber,
    hunk.modifiedEndLineNumber,
  );
  const replacement = origLines.slice(o.start, o.end);
  return [
    ...modLines.slice(0, m.start),
    ...replacement,
    ...modLines.slice(m.end),
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TabbedEditor({
  tabs,
  activeTabPath,
  onTabSelect,
  onTabClose,
  onTabDirtyChange,
  onTabContentChange,
  onFileSaved,
}: TabbedEditorProps) {
  const { isDark } = useTheme();
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const activeTabPathRef = useRef(activeTabPath);
  activeTabPathRef.current = activeTabPath;

  const [saving, setSaving] = useState(false);
  const [hasSelection, setHasSelection] = useState(false);

  /**
   * Paths whose tabs are currently in "Preview" mode instead of code editor.
   * Only applies to previewable files (images, md, pdf, csv).
   */
  const [previewPaths, setPreviewPaths] = useState<Set<string>>(new Set());

  const togglePreview = useCallback((path: string) => {
    setPreviewPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  // Default is Code mode; user manually toggles to Preview via the Eye button.

  /**
   * Paths currently being reverted via Undo — suppress watcher-triggered diffs
   * for these paths so the revert write doesn't immediately create a new diff.
   */
  const undoInProgressRef = useRef<Set<string>>(new Set());

  /**
   * Pending diffs keyed by file path, persisted per-agent. When the agent
   * modifies a file while it is open, we capture the original baseline and
   * the new (modified) content so the user can review. After a reload, the
   * `modified` side is null until the hydrate effect re-fetches it.
   */
  const { selectedAgent } = useAgentStore();
  const pendingDiffs = useCurrentDiffs();
  const { setDiff, removeDiff, updateDiffModified, updateDiffOriginal } =
    useCodingTabsStore();

  /**
   * Per-hunk Keep / Undo widgets are rendered as React JSX in an
   * absolutely-positioned overlay layered on top of the DiffEditor,
   * NOT inside Monaco's DOM. Earlier attempts using Monaco view zones
   * or content widgets to host the buttons hit a wall: Monaco's mouse
   * handler intercepts mousedown on its own children and prevents the
   * click from firing. Rendering buttons outside Monaco entirely makes
   * clicks fire normally.
   *
   * The empty view zones added below exist only to push code lines
   * apart so the overlay has a 22px-tall gap to sit in (no source-text
   * overlap). Monaco reports the pixel-top of each zone via
   * `onDomNodeTop`, which is what drives the overlay positions.
   */
  const diffEditorRef = useRef<MonacoEditor.IStandaloneDiffEditor | null>(null);
  const hunkZoneIdsRef = useRef<string[]>([]);

  // Each overlay: the line-change it represents, plus the pixel-top of
  // its view zone (kept in sync via onDomNodeTop and editor scroll).
  interface HunkOverlay {
    zoneId: string;
    change: MonacoEditor.ILineChange;
    top: number;
  }
  const [hunkOverlays, setHunkOverlays] = useState<HunkOverlay[]>([]);

  const activeTab = tabs.find((t) => t.path === activeTabPath) ?? null;
  const activeDiffRaw = activeTabPath ? pendingDiffs[activeTabPath] : undefined;
  // Only render the diff editor once the modified side has been hydrated.
  const activeDiff =
    activeDiffRaw && activeDiffRaw.modified !== null
      ? { original: activeDiffRaw.original, modified: activeDiffRaw.modified }
      : undefined;

  // Hydrate the `modified` side of any persisted diff by re-reading the
  // current disk content. Drop diffs whose file no longer exists.
  useEffect(() => {
    let cancelled = false;
    const toHydrate = Object.entries(pendingDiffs).filter(
      ([, d]) => d.modified === null,
    );
    if (toHydrate.length === 0) return undefined;

    void Promise.all(
      toHydrate.map(async ([path]) => {
        try {
          const result = await workspaceApi.loadCodeFile(path);
          return { path, modified: result.content ?? "", ok: true };
        } catch {
          return { path, modified: "", ok: false };
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      for (const r of results) {
        if (r.ok) {
          updateDiffModified(selectedAgent, r.path, r.modified);
        } else {
          removeDiff(selectedAgent, r.path);
        }
      }
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  // ---- Monaco setup -------------------------------------------------------

  const handleBeforeMount = useCallback((monaco: Monaco) => {
    monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
      target: monaco.languages.typescript.ScriptTarget.ESNext,
      moduleResolution: monaco.languages.typescript.ModuleResolutionKind.NodeJs,
      allowSyntheticDefaultImports: true,
      jsx: monaco.languages.typescript.JsxEmit.ReactJSX,
    });
    monaco.languages.typescript.typescriptDefaults.setDiagnosticsOptions({
      noSemanticValidation: false,
      noSyntaxValidation: false,
    });
  }, []);

  const handleMount = useCallback(
    (editor: MonacoEditor.IStandaloneCodeEditor) => {
      editorRef.current = editor;

      editor.onDidChangeCursorSelection((e) => {
        const sel = e.selection;
        setHasSelection(
          !sel.isEmpty() ||
            sel.startLineNumber !== sel.endLineNumber ||
            sel.startColumn !== sel.endColumn,
        );
      });
    },
    [],
  );

  /**
   * Cmd/Ctrl+C in any of our editors (normal or diff-modified): let
   * Monaco run its native copy (plain text → system clipboard), then
   * snapshot the selection so the Chat composer's paste handler can
   * swap in `path:line[-line]` format when the same text lands in the
   * chat textarea.
   *
   * Registered at document level (capture) so it fires regardless of
   * which Monaco instance owns the copy (regular vs diff editor) and
   * regardless of bubbling quirks.
   */
  useEffect(() => {
    const onCopy = () => {
      // Any copy event that does NOT originate from our editor
      // invalidates the cache — otherwise a same-text copy elsewhere
      // (e.g. a markdown preview in the same page) would still trigger
      // the formatted swap on the next chat paste.
      const path = activeTabPathRef.current;
      const editor: MonacoEditor.IStandaloneCodeEditor | null =
        diffEditorRef.current?.getModifiedEditor() ?? editorRef.current;
      if (!path || !editor || !editor.hasTextFocus()) {
        clearLastEditorCopy();
        return;
      }
      const sel = editor.getSelection();
      const model = editor.getModel();
      if (!sel || !model || sel.isEmpty()) {
        clearLastEditorCopy();
        return;
      }
      const { mode, code, startLine, endLine } = detectCopyMode(sel, model);
      const formatted = formatSelectionForChat(
        path,
        code,
        startLine,
        endLine,
        mode,
      );
      if (formatted !== code) {
        setLastEditorCopy({ text: code, formatted, ts: Date.now() });
      } else {
        clearLastEditorCopy();
      }
    };
    document.addEventListener("copy", onCopy, true);
    return () => document.removeEventListener("copy", onCopy, true);
  }, []);

  /**
   * Re-create per-hunk spacer view zones to match the diff editor's
   * current line changes, and seed the React overlay state for those
   * zones. Called on mount and on every onDidUpdateDiff so spacers /
   * overlays stay aligned with the diff state.
   *
   * The zones themselves are empty 22px placeholders — they exist only
   * to push code lines apart so the floating overlay (rendered in JSX
   * outside Monaco) has a gap to sit in without covering source text.
   */
  const refreshHunkWidgets = useCallback(() => {
    const diffEditor = diffEditorRef.current;
    if (!diffEditor) return;
    const modifiedEditor = diffEditor.getModifiedEditor();

    // Tear down previous spacer zones before adding fresh ones.
    if (hunkZoneIdsRef.current.length > 0) {
      modifiedEditor.changeViewZones((accessor) => {
        for (const zoneId of hunkZoneIdsRef.current) {
          accessor.removeZone(zoneId);
        }
      });
      hunkZoneIdsRef.current = [];
    }

    const lineChanges = diffEditor.getLineChanges();
    if (!lineChanges || lineChanges.length === 0) {
      setHunkOverlays([]);
      return;
    }

    // Build the next overlay list in a single React state update.
    // Each zone is empty (just creates 22px of vertical space). Monaco
    // calls onDomNodeTop with the zone's pixel-top whenever it changes
    // (initial layout, scroll, content edits) — we use that to drive
    // the React overlay's `top: …px` style.
    const next: HunkOverlay[] = [];
    modifiedEditor.changeViewZones((accessor) => {
      for (const change of lineChanges) {
        // afterLineNumber: 0 means "before line 1". For modification or
        // pure addition, anchor the zone right above modifiedStart. For
        // pure deletion (modifiedEndLineNumber === 0) Monaco reports
        // the line *after* which the deletion appears, so we anchor
        // there directly — the zone shows at the deletion gap.
        const afterLine =
          change.modifiedEndLineNumber === 0
            ? change.modifiedStartLineNumber
            : change.modifiedStartLineNumber - 1;

        const spacer = document.createElement("div");
        const zoneId = accessor.addZone({
          afterLineNumber: Math.max(0, afterLine),
          heightInPx: 22,
          domNode: spacer,
          onDomNodeTop: (top) => {
            setHunkOverlays((prev) =>
              prev.map((o) => (o.zoneId === zoneId ? { ...o, top } : o)),
            );
          },
        });
        hunkZoneIdsRef.current.push(zoneId);
        next.push({ zoneId, change, top: 0 });
      }
    });
    setHunkOverlays(next);
  }, []);

  /**
   * Wire up per-hunk spacer view zones on the modified (right) pane of
   * the DiffEditor. Monaco's `onDomNodeTop` callback (set per zone in
   * refreshHunkWidgets) fires whenever a zone's on-screen top changes
   * — including on scroll — so we don't need a separate scroll
   * listener; the React overlay tops stay in sync automatically.
   */
  const handleDiffMount: DiffOnMount = useCallback(
    (diffEditor) => {
      diffEditorRef.current = diffEditor;
      diffEditor.onDidUpdateDiff(() => refreshHunkWidgets());
      // Initial pass — Monaco may have already finished diffing by the
      // time we mount (small files), so run once eagerly.
      refreshHunkWidgets();
    },
    [refreshHunkWidgets],
  );

  // ---- Save ---------------------------------------------------------------

  const handleSave = useCallback(async () => {
    if (!activeTabPath || saving) return;
    setSaving(true);
    try {
      const content = editorRef.current?.getValue() ?? activeTab?.content ?? "";
      await workspaceApi.saveCodeFile(activeTabPath, content);
      onTabDirtyChange(activeTabPath, false);
      onFileSaved?.(activeTabPath);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }, [activeTabPath, saving, activeTab, onTabDirtyChange, onFileSaved]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        void handleSave();
      }
    },
    [handleSave],
  );

  // ---- Copy to Chat -------------------------------------------------------

  const handleCopyToChat = useCallback(() => {
    const editor = editorRef.current;
    if (!editor || !activeTabPath) return;
    const selection = editor.getSelection();
    if (!selection) return;
    const model = editor.getModel();
    if (!model) return;
    // Empty selection ≡ whole-file copy via button.
    if (selection.isEmpty()) {
      appendToChat(
        formatSelectionForChat(activeTabPath, "", 1, 1, "whole-file"),
      );
      return;
    }
    const { mode, code, startLine, endLine } = detectCopyMode(selection, model);
    appendToChat(
      formatSelectionForChat(activeTabPath, code, startLine, endLine, mode),
    );
  }, [activeTabPath]);

  // ---- Diff actions -------------------------------------------------------

  /**
   * Keep: dismiss the diff and accept the new (modified) content.
   * The file on disk is already updated; we just clear the diff state.
   */
  const handleKeep = useCallback(() => {
    const diff = pendingDiffs[activeTabPath];
    if (!diff || diff.modified === null) return;
    removeDiff(selectedAgent, activeTabPath);
    onTabContentChange(activeTabPath, diff.modified);
    onTabDirtyChange(activeTabPath, false);
  }, [
    activeTabPath,
    pendingDiffs,
    selectedAgent,
    removeDiff,
    onTabContentChange,
    onTabDirtyChange,
  ]);

  /**
   * Undo: dismiss the diff and revert to the original content.
   * Writes the original content back to disk.
   */
  const handleUndo = useCallback(async () => {
    const diff = pendingDiffs[activeTabPath];
    if (!diff) return;
    removeDiff(selectedAgent, activeTabPath);
    // Suppress the watcher so the revert write doesn't spawn a new diff
    undoInProgressRef.current.add(activeTabPath);
    try {
      await workspaceApi.saveCodeFile(activeTabPath, diff.original);
    } catch {
      // ignore – UI is already restored
    } finally {
      // Give the SSE watcher a moment to fire (and be suppressed) before re-enabling
      setTimeout(() => undoInProgressRef.current.delete(activeTabPath), 1500);
    }
    onTabContentChange(activeTabPath, diff.original);
    onTabDirtyChange(activeTabPath, false);
  }, [
    activeTabPath,
    pendingDiffs,
    selectedAgent,
    removeDiff,
    onTabContentChange,
    onTabDirtyChange,
  ]);

  /**
   * Keep a single hunk: bake its modified content into the original
   * baseline. The kept block stops being a diff; remaining hunks stay.
   * If this collapses the whole diff, drop it entirely.
   */
  const handleKeepHunk = useCallback(
    (hunk: Hunk) => {
      const diff = pendingDiffs[activeTabPath];
      if (!diff || diff.modified === null) return;
      const newOriginal = applyKeepHunk(diff.original, diff.modified, hunk);
      if (newOriginal === diff.modified) {
        removeDiff(selectedAgent, activeTabPath);
        onTabContentChange(activeTabPath, diff.modified);
        onTabDirtyChange(activeTabPath, false);
      } else {
        updateDiffOriginal(selectedAgent, activeTabPath, newOriginal);
      }
    },
    [
      activeTabPath,
      pendingDiffs,
      selectedAgent,
      removeDiff,
      updateDiffOriginal,
      onTabContentChange,
      onTabDirtyChange,
    ],
  );

  /**
   * Undo a single hunk: revert its modified content to the original and
   * persist that to disk. Other hunks remain. If the file ends up equal
   * to the original baseline, drop the diff entirely.
   */
  const handleUndoHunk = useCallback(
    async (hunk: Hunk) => {
      const diff = pendingDiffs[activeTabPath];
      if (!diff || diff.modified === null) return;
      const newModified = applyUndoHunk(diff.original, diff.modified, hunk);

      undoInProgressRef.current.add(activeTabPath);
      try {
        await workspaceApi.saveCodeFile(activeTabPath, newModified);
      } catch {
        // ignore — UI state is updated below regardless
      } finally {
        setTimeout(() => undoInProgressRef.current.delete(activeTabPath), 1500);
      }

      if (newModified === diff.original) {
        removeDiff(selectedAgent, activeTabPath);
      } else {
        updateDiffModified(selectedAgent, activeTabPath, newModified);
      }
      onTabContentChange(activeTabPath, newModified);
      onTabDirtyChange(activeTabPath, false);
    },
    [
      activeTabPath,
      pendingDiffs,
      selectedAgent,
      removeDiff,
      updateDiffModified,
      onTabContentChange,
      onTabDirtyChange,
    ],
  );

  // When the diff goes away (Keep all, Undo all, or final hunk
  // resolved), Monaco unmounts the DiffEditor — drop our local
  // bookkeeping. Monaco disposes its own view zones on unmount.
  const hasActiveDiff = activeDiff != null;
  useEffect(() => {
    if (hasActiveDiff) return;
    hunkZoneIdsRef.current = [];
    diffEditorRef.current = null;
    setHunkOverlays([]);
  }, [hasActiveDiff]);

  // ---- File-watch: show inline diff instead of silent reload ---------------

  useWorkspaceWatch((events) => {
    const path = activeTabPathRef.current;
    if (!path) return;

    const tab = tabs.find((t) => t.path === path);
    // If the user has unsaved edits, don't overwrite them
    if (tab?.dirty) return;
    // If an undo revert write is in flight, don't create a diff
    if (undoInProgressRef.current.has(path)) return;

    // Treat `added` the same as `modified` for an already-open tab: atomic
    // saves (e.g. macOS `sed -i ''`, vim, VSCode) replace the file via
    // rename, which FSEvents reports as a creation rather than a content
    // change. From the editor's POV, the path's contents just differ.
    const affected = events.some(
      (e) =>
        (e.change === "modified" || e.change === "added") &&
        e.path.replace(/\\/g, "/") === path.replace(/\\/g, "/"),
    );
    if (!affected) return;

    const existingDiff = pendingDiffs[path];

    workspaceApi
      .loadCodeFile(path)
      .then((res) => {
        const newModified = res.content ?? "";

        if (existingDiff) {
          // There is already a pending diff — update only the modified side so
          // the user sees the cumulative change (original → latest agent edit).
          if (newModified === existingDiff.modified) return;
          updateDiffModified(selectedAgent, path, newModified);
        } else {
          // First edit — capture current editor content as baseline original.
          const originalContent =
            editorRef.current?.getValue() ?? tab?.content ?? "";
          if (newModified === originalContent) return;
          setDiff(selectedAgent, path, {
            original: originalContent,
            modified: newModified,
          });
        }
      })
      .catch(() => undefined);
  });

  // ---- Empty state --------------------------------------------------------

  if (tabs.length === 0) {
    return (
      <div className={styles.empty}>
        <FileCode size={36} className={styles.emptyIcon} />
        <p className={styles.emptyText}>Select a file to open</p>
      </div>
    );
  }

  const shortPath = (p: string) => p.split("/").slice(-2).join("/");

  const activeIsPreviewable = activeTabPath
    ? isPreviewable(activeTabPath)
    : false;
  const activeInPreview = activeTabPath
    ? previewPaths.has(activeTabPath)
    : false;

  return (
    <div className={styles.wrap} onKeyDown={handleKeyDown}>
      {/* ── Tab bar ────────────────────────────────────────────────────── */}
      <div className={styles.tabBar}>
        {tabs.map((tab) => {
          const active = tab.path === activeTabPath;
          const hasDiff = Boolean(pendingDiffs[tab.path]);
          return (
            <div
              key={tab.path}
              className={`${styles.tab} ${active ? styles.tabActive : ""} ${
                hasDiff ? styles.tabDiff : ""
              }`}
              onClick={() => onTabSelect(tab.path)}
              role="tab"
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && onTabSelect(tab.path)}
              title={tab.path}
            >
              {hasDiff ? (
                <GitCompareArrows size={11} className={styles.diffDot} />
              ) : tab.dirty ? (
                <span className={styles.dirtyDot} />
              ) : null}
              <span className={styles.tabName}>{shortPath(tab.path)}</span>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={(e) => {
                  e.stopPropagation();
                  onTabClose(tab.path);
                }}
                aria-label="Close tab"
              >
                <X size={11} />
              </button>
            </div>
          );
        })}
      </div>

      {/* ── Toolbar ────────────────────────────────────────────────────── */}
      <div className={styles.toolbar}>
        <span className={styles.fileName}>
          {activeTab ? activeTab.path : ""}
        </span>

        {activeDiff ? (
          /* Diff mode: show global Keep all / Undo all */
          <div className={styles.diffActions}>
            <span className={styles.diffLabel}>
              <GitCompareArrows size={12} />
              Agent changed this file
            </span>
            <Tooltip title="Keep all changes in this file">
              <button
                type="button"
                className={`${styles.iconBtn} ${styles.keepBtn}`}
                onClick={handleKeep}
              >
                <Check size={13} />
                Keep all
              </button>
            </Tooltip>
            <Tooltip title="Undo all changes in this file (revert to original)">
              <button
                type="button"
                className={`${styles.iconBtn} ${styles.undoBtn}`}
                onClick={() => void handleUndo()}
              >
                <RotateCcw size={13} />
                Undo all
              </button>
            </Tooltip>
          </div>
        ) : (
          /* Normal mode: Preview toggle + Copy-to-Chat + Save */
          <div className={styles.toolbarRight}>
            {activeIsPreviewable && (
              <Tooltip
                title={activeInPreview ? "Switch to Code" : "Open Preview"}
              >
                <button
                  type="button"
                  className={`${styles.iconBtn} ${
                    activeInPreview ? styles.previewActiveBtn : ""
                  }`}
                  onClick={() => togglePreview(activeTabPath)}
                >
                  {activeInPreview ? <Code2 size={13} /> : <Eye size={13} />}
                </button>
              </Tooltip>
            )}
            {!activeInPreview && (
              <>
                <Tooltip
                  title={
                    hasSelection
                      ? "Copy selection to Chat"
                      : "Copy file to Chat"
                  }
                >
                  <button
                    type="button"
                    className={styles.iconBtn}
                    onClick={handleCopyToChat}
                    disabled={!activeTabPath}
                  >
                    <MessageSquarePlus size={13} />
                  </button>
                </Tooltip>
                <Tooltip title="Save (Cmd+S)">
                  <button
                    type="button"
                    className={styles.iconBtn}
                    onClick={handleSave}
                    disabled={saving || !activeTab?.dirty}
                  >
                    <Save size={13} />
                  </button>
                </Tooltip>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Editor area ────────────────────────────────────────────────── */}
      <div className={styles.editor}>
        {activeTab && activeInPreview ? (
          /* ── Preview mode (image / markdown / pdf / csv) ─────────────── */
          <FilePreview filePath={activeTab.path} content={activeTab.content} />
        ) : (
          activeTab &&
          (activeDiff ? (
            /* ── Inline diff view (VS Code "Copilot Edits" style) ─────── */
            <div className={styles.diffWrap}>
              <DiffEditor
                height="100%"
                original={activeDiff.original}
                modified={activeDiff.modified}
                language={getLanguage(activeTab.path)}
                theme={isDark ? "vs-dark" : "light"}
                beforeMount={handleBeforeMount}
                onMount={handleDiffMount}
                options={{
                  renderSideBySide: false,
                  readOnly: false,
                  originalEditable: false,
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  wordWrap: "off",
                  renderOverviewRuler: false,
                }}
              />
              {/* Per-hunk Keep / Undo overlays — rendered as React JSX
                  OUTSIDE Monaco's DOM (positioned over the editor). The
                  buttons must live outside Monaco because Monaco's
                  mouseHandler captures mousedown on its own children
                  (view zones, content widgets) and prevents the click
                  from firing. */}
              {hunkOverlays.map((ov) => (
                <div
                  key={ov.zoneId}
                  className={styles.hunkWidget}
                  style={{ top: ov.top }}
                >
                  <button
                    type="button"
                    className={`${styles.hunkBtn} ${styles.hunkKeepBtn}`}
                    onClick={() => handleKeepHunk(ov.change)}
                  >
                    <Check size={11} style={{ marginRight: 4 }} />
                    Keep
                  </button>
                  <button
                    type="button"
                    className={`${styles.hunkBtn} ${styles.hunkUndoBtn}`}
                    onClick={() => void handleUndoHunk(ov.change)}
                  >
                    <RotateCcw size={11} style={{ marginRight: 4 }} />
                    Undo
                  </button>
                </div>
              ))}
            </div>
          ) : (
            /* ── Normal editor ──────────────────────────────────────────── */
            <Editor
              height="100%"
              path={activeTab.path}
              defaultValue={activeTab.content}
              language={getLanguage(activeTab.path)}
              theme={isDark ? "vs-dark" : "light"}
              beforeMount={handleBeforeMount}
              onMount={handleMount}
              onChange={(v) => {
                onTabContentChange(activeTabPath, v ?? "");
                onTabDirtyChange(activeTabPath, true);
              }}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
                wordWrap: "off",
                tabSize: 2,
                renderLineHighlight: "line",
                suggestOnTriggerCharacters: true,
                acceptSuggestionOnCommitCharacter: true,
                quickSuggestions: true,
                parameterHints: { enabled: true },
                hover: { enabled: true },
                gotoLocation: { multiple: "goto" },
              }}
            />
          ))
        )}
      </div>
    </div>
  );
}
