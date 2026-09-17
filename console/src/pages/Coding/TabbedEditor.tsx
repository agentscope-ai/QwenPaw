/**
 * TabbedEditor – multi-file Monaco editor with:
 *   • File tabs (close, dirty indicator, pending-diff indicator)
 *   • Monaco model-per-path (undo history & cursor persist on tab switch)
 *   • Inline Diff view when Agent modifies the open file:
 *       - Switches to DiffEditor (renderSideBySide: false → VS Code inline style)
 *       - Per-hunk "Keep"/"Undo" widgets + global "Keep all"/"Undo all"
 *   • Preview mode for images, Markdown, HTML, PDF, CSV (toggle per tab)
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
  Download,
  Eye,
  FileCode,
  GitCompareArrows,
  MessageSquarePlus,
  RotateCcw,
  Save,
  X,
} from "lucide-react";
import { Dropdown, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import FilePreview, { isPreviewable } from "./FilePreview";
import { workspaceApi } from "../../api/modules/workspace";
import { useWorkspaceWatch } from "../../hooks/useWorkspaceWatch";
import { useTheme } from "../../contexts/ThemeContext";
import { setTextareaValue } from "../Chat/utils";
import { clearLastEditorCopy, setLastEditorCopy } from "./lastEditorCopy";
import {
  useCodingTabsStore,
  useDiffsForScope,
  type EditorTab,
} from "../../stores/codingTabsStore";
import {
  detectCopyMode,
  formatSelectionForChat,
  getEditorLanguage,
  visibleEditorPath,
} from "./editorCopyFormatting";
import styles from "./TabbedEditor.module.less";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type { EditorTab };

interface TabbedEditorProps {
  tabs: EditorTab[];
  activeTabPath: string;
  scopeKey: string;
  onTabSelect: (path: string) => void;
  onTabClose: (path: string) => void;
  onCloseOtherTabs: (path: string) => void;
  onTabDirtyChange: (path: string, dirty: boolean) => void;
  onTabContentChange: (path: string, content: string) => void;
  onFileSaved?: (path: string) => void;
  onLoadFile?: (path: string) => Promise<string>;
  onSaveFile?: (path: string, content: string) => Promise<void>;
  onDownloadFile?: (path: string) => Promise<void>;
  chatId?: string;
  projectDirOverride?: string;
  navigation?: {
    path: string;
    line: number;
    endLine: number;
    column?: number;
    sequence: number;
  } | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  scopeKey,
  onTabSelect,
  onTabClose,
  onCloseOtherTabs,
  onTabDirtyChange,
  onTabContentChange,
  onFileSaved,
  onLoadFile,
  onSaveFile,
  onDownloadFile,
  chatId,
  projectDirOverride,
  navigation,
}: TabbedEditorProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null);
  const tabElementsRef = useRef(new Map<string, HTMLDivElement>());
  const activeTabPathRef = useRef(activeTabPath);
  const activeDisplayPathRef = useRef(activeTabPath);
  const navigationRef = useRef(navigation);
  activeTabPathRef.current = activeTabPath;
  navigationRef.current = navigation;

  const [saving, setSaving] = useState(false);
  const [resolvingDiff, setResolvingDiff] = useState(false);
  const [hasSelection, setHasSelection] = useState(false);

  /**
   * Paths whose tabs are currently in "Preview" mode instead of code editor.
   * Every file opens Preview-first. Text files enter Monaco only after the
   * user explicitly selects Edit.
   */
  const [previewPaths, setPreviewPaths] = useState<Set<string>>(new Set());

  /**
   * Tracks files that the user has manually toggled preview mode for.
   * Prevents the auto-preview useEffect from overriding user's choice.
   */
  const userToggledPathsRef = useRef<Set<string>>(new Set());

  /**
   * Clean up userToggledPathsRef when tabs are closed.
   * Prevents memory leak and ensures reopened files get auto-preview again.
   */
  useEffect(() => {
    const openPaths = new Set(tabs.map((t) => t.path));
    const toRemove: string[] = [];

    for (const path of userToggledPathsRef.current) {
      if (!openPaths.has(path)) {
        toRemove.push(path);
      }
    }

    for (const path of toRemove) {
      userToggledPathsRef.current.delete(path);
    }
  }, [tabs]);

  /**
   * Auto-enable preview mode for newly opened files.
   * Skips files that the user has manually toggled.
   */
  useEffect(() => {
    const newPreviewPaths = new Set(previewPaths);
    let hasChanges = false;

    for (const tab of tabs) {
      // Skip if user has manually toggled this file
      if (userToggledPathsRef.current.has(tab.path)) {
        continue;
      }
      if (!newPreviewPaths.has(tab.path)) {
        newPreviewPaths.add(tab.path);
        hasChanges = true;
      }
    }

    if (hasChanges) {
      setPreviewPaths(newPreviewPaths);
    }
  }, [tabs, previewPaths]);

  const togglePreview = useCallback((path: string) => {
    // Mark this file as user-toggled so auto-preview won't override
    userToggledPathsRef.current.add(path);
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

  useEffect(() => {
    if (!navigation || navigation.path !== activeTabPath) return;
    userToggledPathsRef.current.add(navigation.path);
    setPreviewPaths((previous) => {
      if (!previous.has(navigation.path)) return previous;
      const next = new Set(previous);
      next.delete(navigation.path);
      return next;
    });
  }, [activeTabPath, navigation]);

  // Previewable files auto-enter preview mode; user can toggle back to Code via Eye button.

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
  const pendingDiffs = useDiffsForScope(scopeKey);
  const {
    setDiff,
    removeDiff,
    updateDiffModified,
    updateDiffOriginal,
    resolveDiff,
  } = useCodingTabsStore();

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
  const diffModifiedListenerRef = useRef<{ dispose: () => void } | null>(null);
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
  const activeDisplayPath = activeTab
    ? activeTab.displayPath ?? visibleEditorPath(activeTab.path)
    : "";
  const activeWatchRoot =
    activeTab?.workspaceRoot ??
    (activeTab?.source === "profile" ? "workspace" : "project");
  const watchEnabled =
    activeTab?.source === "workspace" || activeTab?.source === "profile";
  activeDisplayPathRef.current = activeDisplayPath;
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
          const modified = onLoadFile
            ? await onLoadFile(path)
            : (await workspaceApi.loadCodeFile(path)).content;
          return { path, modified, ok: true };
        } catch {
          return { path, modified: "", ok: false };
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      for (const r of results) {
        if (r.ok) {
          updateDiffModified(scopeKey, r.path, r.modified);
        } else {
          removeDiff(scopeKey, r.path);
        }
      }
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onLoadFile, scopeKey]);

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

  const revealNavigation = useCallback(
    (editor: MonacoEditor.IStandaloneCodeEditor) => {
      const target = navigationRef.current;
      if (!target || target.path !== activeTabPathRef.current) return;
      const model = editor.getModel();
      if (!model) return;
      const line = Math.min(Math.max(target.line, 1), model.getLineCount());
      const endLine = Math.min(
        Math.max(target.endLine, line),
        model.getLineCount(),
      );
      const column = Math.min(
        Math.max(target.column ?? 1, 1),
        model.getLineMaxColumn(line),
      );
      editor.setSelection({
        startLineNumber: line,
        startColumn: column,
        endLineNumber: endLine,
        endColumn: model.getLineMaxColumn(endLine),
      });
      editor.revealLinesInCenter(line, endLine);
      editor.focus();
    },
    [],
  );

  const handleMount = useCallback(
    (editor: MonacoEditor.IStandaloneCodeEditor) => {
      editorRef.current = editor;
      revealNavigation(editor);

      editor.onDidChangeCursorSelection((e) => {
        const sel = e.selection;
        setHasSelection(
          !sel.isEmpty() ||
            sel.startLineNumber !== sel.endLineNumber ||
            sel.startColumn !== sel.endColumn,
        );
      });
    },
    [revealNavigation],
  );

  useEffect(() => {
    const editor =
      diffEditorRef.current?.getModifiedEditor() ?? editorRef.current;
    if (editor) revealNavigation(editor);
  }, [navigation, revealNavigation]);

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
      const path = activeDisplayPathRef.current;
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
      editorRef.current = null;
      diffModifiedListenerRef.current?.dispose();
      const modifiedEditor = diffEditor.getModifiedEditor();
      revealNavigation(modifiedEditor);
      diffModifiedListenerRef.current = modifiedEditor.onDidChangeModelContent(
        () => {
          const path = activeTabPathRef.current;
          if (!path) return;
          const currentDiff =
            useCodingTabsStore.getState().diffsByAgent[scopeKey]?.[path];
          const modified = modifiedEditor.getValue();
          if (currentDiff && currentDiff.modified !== modified) {
            updateDiffModified(scopeKey, path, modified);
          }
        },
      );
      diffEditor.onDidUpdateDiff(() => refreshHunkWidgets());
      // Initial pass — Monaco may have already finished diffing by the
      // time we mount (small files), so run once eagerly.
      refreshHunkWidgets();
    },
    [refreshHunkWidgets, revealNavigation, scopeKey, updateDiffModified],
  );

  // ---- Save ---------------------------------------------------------------

  const handleSave = useCallback(async () => {
    if (
      !activeTabPath ||
      saving ||
      resolvingDiff ||
      activeDiff ||
      activeTab?.readOnly
    ) {
      return;
    }
    setSaving(true);
    try {
      const content = activeTab?.content ?? "";
      if (onSaveFile) {
        await onSaveFile(activeTabPath, content);
      } else {
        await workspaceApi.saveCodeFile(activeTabPath, content);
      }
      onTabDirtyChange(activeTabPath, false);
      onFileSaved?.(activeTabPath);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }, [
    activeTabPath,
    saving,
    resolvingDiff,
    activeDiff,
    activeTab,
    onTabDirtyChange,
    onFileSaved,
    onSaveFile,
  ]);

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
    if (!editor || !activeTabPath || !activeDisplayPath) return;
    const selection = editor.getSelection();
    if (!selection) return;
    const model = editor.getModel();
    if (!model) return;
    // Empty selection ≡ whole-file copy via button.
    if (selection.isEmpty()) {
      appendToChat(
        formatSelectionForChat(activeDisplayPath, "", 1, 1, "whole-file"),
      );
      return;
    }
    const { mode, code, startLine, endLine } = detectCopyMode(selection, model);
    appendToChat(
      formatSelectionForChat(activeDisplayPath, code, startLine, endLine, mode),
    );
  }, [activeDisplayPath, activeTabPath]);

  // Keep the hidden button implementation available for future restoration.
  void MessageSquarePlus;
  void hasSelection;
  void handleCopyToChat;

  // ---- Diff actions -------------------------------------------------------

  /**
   * Keep: dismiss the diff and accept the new (modified) content.
   * The file on disk is already updated; we just clear the diff state.
   */
  const handleKeep = useCallback(async () => {
    const diff = pendingDiffs[activeTabPath];
    if (!diff || diff.modified === null || resolvingDiff) return;
    setResolvingDiff(true);
    try {
      if (onSaveFile) {
        await onSaveFile(activeTabPath, diff.modified);
      } else {
        await workspaceApi.saveCodeFile(activeTabPath, diff.modified);
      }
      resolveDiff(scopeKey, activeTabPath, diff.modified);
      onFileSaved?.(activeTabPath);
    } catch {
      return;
    } finally {
      setResolvingDiff(false);
    }
  }, [
    activeTabPath,
    pendingDiffs,
    resolvingDiff,
    scopeKey,
    resolveDiff,
    onFileSaved,
    onSaveFile,
  ]);

  /**
   * Undo: dismiss the diff and revert to the original content.
   * Writes the original content back to disk.
   */
  const handleUndo = useCallback(async () => {
    const diff = pendingDiffs[activeTabPath];
    if (!diff || resolvingDiff) return;
    setResolvingDiff(true);
    // Suppress the watcher so the revert write doesn't spawn a new diff
    undoInProgressRef.current.add(activeTabPath);
    try {
      if (onSaveFile) {
        await onSaveFile(activeTabPath, diff.original);
      } else {
        await workspaceApi.saveCodeFile(activeTabPath, diff.original);
      }
      resolveDiff(scopeKey, activeTabPath, diff.original);
      onFileSaved?.(activeTabPath);
    } catch {
      return;
    } finally {
      // Give the SSE watcher a moment to fire (and be suppressed) before re-enabling
      setTimeout(() => undoInProgressRef.current.delete(activeTabPath), 1500);
      setResolvingDiff(false);
    }
  }, [
    activeTabPath,
    pendingDiffs,
    resolvingDiff,
    scopeKey,
    resolveDiff,
    onFileSaved,
    onSaveFile,
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
        resolveDiff(scopeKey, activeTabPath, diff.modified);
      } else {
        updateDiffOriginal(scopeKey, activeTabPath, newOriginal);
      }
    },
    [activeTabPath, pendingDiffs, scopeKey, resolveDiff, updateDiffOriginal],
  );

  /**
   * Undo a single hunk: revert its modified content to the original and
   * persist that to disk. Other hunks remain. If the file ends up equal
   * to the original baseline, drop the diff entirely.
   */
  const handleUndoHunk = useCallback(
    async (hunk: Hunk) => {
      const diff = pendingDiffs[activeTabPath];
      if (!diff || diff.modified === null || resolvingDiff) return;
      const newModified = applyUndoHunk(diff.original, diff.modified, hunk);

      setResolvingDiff(true);
      undoInProgressRef.current.add(activeTabPath);
      try {
        if (onSaveFile) {
          await onSaveFile(activeTabPath, newModified);
        } else {
          await workspaceApi.saveCodeFile(activeTabPath, newModified);
        }
        if (newModified === diff.original) {
          resolveDiff(scopeKey, activeTabPath, newModified);
        } else {
          updateDiffModified(scopeKey, activeTabPath, newModified);
          onTabContentChange(activeTabPath, newModified);
          onTabDirtyChange(activeTabPath, false);
        }
        onFileSaved?.(activeTabPath);
      } catch {
        return;
      } finally {
        setTimeout(() => undoInProgressRef.current.delete(activeTabPath), 1500);
        setResolvingDiff(false);
      }
    },
    [
      activeTabPath,
      pendingDiffs,
      resolvingDiff,
      scopeKey,
      resolveDiff,
      updateDiffModified,
      onTabContentChange,
      onTabDirtyChange,
      onFileSaved,
      onSaveFile,
    ],
  );

  // When the diff goes away (Keep all, Undo all, or final hunk
  // resolved), Monaco unmounts the DiffEditor — drop our local
  // bookkeeping. Monaco disposes its own view zones on unmount.
  const hasActiveDiff = activeDiff != null;
  useEffect(() => {
    if (hasActiveDiff) return;
    diffModifiedListenerRef.current?.dispose();
    diffModifiedListenerRef.current = null;
    hunkZoneIdsRef.current = [];
    diffEditorRef.current = null;
    setHunkOverlays([]);
  }, [hasActiveDiff]);

  useEffect(
    () => () => {
      diffModifiedListenerRef.current?.dispose();
    },
    [],
  );

  // ---- File-watch: show inline diff instead of silent reload ---------------

  useWorkspaceWatch(
    (events) => {
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
          e.path.replace(/\\/g, "/") ===
            (tab?.displayPath ?? visibleEditorPath(path)).replace(/\\/g, "/"),
      );
      if (!affected) return;

      const existingDiff = pendingDiffs[path];

      const loadFile = onLoadFile
        ? onLoadFile(path)
        : workspaceApi.loadCodeFile(path).then((res) => res.content ?? "");
      void loadFile
        .then((newModified) => {
          if (existingDiff) {
            // There is already a pending diff — update only the modified side so
            // the user sees the cumulative change (original → latest agent edit).
            if (newModified === existingDiff.modified) return;
            updateDiffModified(scopeKey, path, newModified);
          } else {
            // First edit — capture current editor content as baseline original.
            const originalContent = tab?.content ?? "";
            if (newModified === originalContent) return;
            setDiff(scopeKey, path, {
              original: originalContent,
              modified: newModified,
            });
          }
        })
        .catch(() => undefined);
    },
    watchEnabled,
    chatId,
    activeWatchRoot,
    projectDirOverride,
  );

  useEffect(() => {
    const activeTabElement = tabElementsRef.current.get(activeTabPath);
    activeTabElement?.scrollIntoView?.({
      block: "nearest",
      inline: "nearest",
    });
  }, [activeTabPath, tabs.length]);

  // ---- Empty state --------------------------------------------------------

  if (tabs.length === 0) {
    return (
      <div className={styles.empty}>
        <FileCode size={36} className={styles.emptyIcon} />
        <p className={styles.emptyText}>{t("files.selectFile")}</p>
      </div>
    );
  }

  const shortPath = (path: string) => {
    const displayPath = visibleEditorPath(path);
    return displayPath.split("/").slice(-2).join("/");
  };

  const activeInPreview = activeTabPath
    ? previewPaths.has(activeTabPath)
    : false;
  const activeCanEdit =
    Boolean(activeTab) &&
    !activeTab?.readOnly &&
    !["image", "pdf", "binary"].includes(activeTab?.previewKind ?? "text");
  const activeRenderedContent =
    activeDiff?.modified ?? activeTab?.content ?? "";

  return (
    <div className={styles.wrap} onKeyDown={handleKeyDown}>
      {/* ── Tab bar ────────────────────────────────────────────────────── */}
      <div className={styles.tabBar}>
        {tabs.map((tab) => {
          const active = tab.path === activeTabPath;
          const hasDiff = Boolean(pendingDiffs[tab.path]);
          return (
            <Dropdown
              key={tab.path}
              trigger={["contextMenu"]}
              menu={{
                items: [
                  {
                    key: "close",
                    label: t("files.closeTab"),
                    onClick: () => onTabClose(tab.path),
                  },
                  {
                    key: "closeOthers",
                    label: t("files.closeOtherTabs"),
                    disabled: tabs.length <= 1,
                    onClick: () => onCloseOtherTabs(tab.path),
                  },
                ],
              }}
            >
              <div
                ref={(element) => {
                  if (element) tabElementsRef.current.set(tab.path, element);
                  else tabElementsRef.current.delete(tab.path);
                }}
                className={`${styles.tab} ${active ? styles.tabActive : ""} ${
                  hasDiff ? styles.tabDiff : ""
                }`}
                onClick={() => onTabSelect(tab.path)}
                role="tab"
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && onTabSelect(tab.path)}
                title={tab.displayPath ?? visibleEditorPath(tab.path)}
              >
                {hasDiff ? (
                  <GitCompareArrows size={11} className={styles.diffDot} />
                ) : tab.dirty ? (
                  <span className={styles.dirtyDot} />
                ) : null}
                <span className={styles.tabName}>
                  {shortPath(tab.displayPath ?? tab.path)}
                </span>
                <button
                  type="button"
                  className={styles.closeBtn}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTabClose(tab.path);
                  }}
                  aria-label={t("files.closeTab")}
                >
                  <X size={11} />
                </button>
              </div>
            </Dropdown>
          );
        })}
      </div>

      {/* ── Toolbar ────────────────────────────────────────────────────── */}
      <div className={styles.toolbar}>
        <span className={styles.fileName}>{activeDisplayPath}</span>

        <div className={styles.toolbarRight}>
          {activeDiff && (
            <div className={styles.diffActions}>
              <span className={styles.diffLabel}>
                <GitCompareArrows size={12} />
                <span>{t("files.agentChangedFile")}</span>
              </span>
              <Tooltip title={t("files.keepAll")}>
                <button
                  type="button"
                  className={`${styles.iconBtn} ${styles.keepBtn}`}
                  onClick={() => void handleKeep()}
                  disabled={resolvingDiff}
                >
                  <Check size={13} />
                  <span className={styles.actionLabel}>
                    {t("files.keepAll")}
                  </span>
                </button>
              </Tooltip>
              <Tooltip title={t("files.undoAll")}>
                <button
                  type="button"
                  className={`${styles.iconBtn} ${styles.undoBtn}`}
                  onClick={() => void handleUndo()}
                  disabled={resolvingDiff}
                >
                  <RotateCcw size={13} />
                  <span className={styles.actionLabel}>
                    {t("files.undoAll")}
                  </span>
                </button>
              </Tooltip>
            </div>
          )}
          <div className={styles.documentActions}>
            <div className={styles.modeSwitch}>
              <button
                type="button"
                className={activeInPreview ? styles.modeActive : ""}
                onClick={() => {
                  if (!activeInPreview) togglePreview(activeTabPath);
                }}
              >
                <Eye size={12} />
                {t("files.preview")}
              </button>
              {activeCanEdit && (
                <button
                  type="button"
                  className={!activeInPreview ? styles.modeActive : ""}
                  onClick={() => {
                    if (activeInPreview) togglePreview(activeTabPath);
                  }}
                >
                  <Code2 size={12} />
                  {t("files.edit")}
                </button>
              )}
            </div>
            {onDownloadFile && activeTabPath && (
              <Tooltip title={t("files.download")}>
                <button
                  type="button"
                  className={styles.iconBtn}
                  onClick={() => void onDownloadFile(activeTabPath)}
                >
                  <Download size={13} />
                </button>
              </Tooltip>
            )}
            {!activeDiff && !activeInPreview && (
              <>
                {/* <Tooltip
                  title={
                    hasSelection
                      ? t("files.copySelectionToChat")
                      : t("files.copyFileToChat")
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
                </Tooltip> */}
                <Tooltip title={t("common.save")}>
                  <button
                    type="button"
                    className={styles.iconBtn}
                    onClick={handleSave}
                    disabled={
                      saving || !activeTab?.dirty || activeTab?.readOnly
                    }
                  >
                    <Save size={13} />
                  </button>
                </Tooltip>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── Editor area ────────────────────────────────────────────────── */}
      <div className={styles.editor}>
        {activeTab && activeInPreview ? (
          /* ── Preview mode (image / markdown / pdf / csv) ─────────────── */
          isPreviewable(activeDisplayPath) ? (
            <FilePreview
              filePath={activeDisplayPath}
              content={activeRenderedContent}
              chatId={chatId}
              binaryUrl={activeTab.artifactUrl}
              root={activeTab.workspaceRoot}
              projectDirOverride={projectDirOverride}
              workspaceBacked={activeTab.source === "workspace"}
            />
          ) : (
            <pre className={styles.textPreview}>{activeRenderedContent}</pre>
          )
        ) : (
          activeTab &&
          (activeDiff ? (
            /* ── Inline diff view (VS Code "Copilot Edits" style) ─────── */
            <div className={styles.diffWrap}>
              <DiffEditor
                height="100%"
                original={activeDiff.original}
                modified={activeDiff.modified}
                language={getEditorLanguage(activeDisplayPath)}
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
                    disabled={resolvingDiff}
                  >
                    <Check size={11} style={{ marginRight: 4 }} />
                    {t("files.keep")}
                  </button>
                  <button
                    type="button"
                    className={`${styles.hunkBtn} ${styles.hunkUndoBtn}`}
                    onClick={() => void handleUndoHunk(ov.change)}
                    disabled={resolvingDiff}
                  >
                    <RotateCcw size={11} style={{ marginRight: 4 }} />
                    {t("files.undo")}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            /* ── Normal editor ──────────────────────────────────────────── */
            <Editor
              height="100%"
              path={`${scopeKey}/${activeTab.path}`}
              value={activeTab.content}
              language={getEditorLanguage(activeDisplayPath)}
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
                readOnly: activeTab.readOnly,
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
