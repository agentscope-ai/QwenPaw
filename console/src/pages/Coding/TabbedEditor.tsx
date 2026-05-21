/**
 * TabbedEditor – multi-file Monaco editor with:
 *   • File tabs (close, dirty indicator, pending-diff indicator)
 *   • Monaco model-per-path (undo history & cursor persist on tab switch)
 *   • Inline Diff view when Agent modifies the open file:
 *       - Switches to DiffEditor (renderSideBySide: false → VS Code inline style)
 *       - "Keep" accepts the new content; "Undo" reverts to original
 *   • Preview mode for images, Markdown, PDF, CSV (toggle per tab)
 *   • Ctrl/Cmd+C copies code with @file:Lx-y context for Chat injection
 *   • Cmd/Ctrl+S to save
 */

import { useCallback, useRef, useState } from "react";
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
import styles from "./TabbedEditor.module.less";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EditorTab {
  path: string;
  content: string;
  dirty: boolean;
}

/** Pending diff produced when the agent modifies a file externally. */
interface PendingDiff {
  original: string;
  modified: string;
}

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

function formatSelectionForChat(
  filePath: string,
  code: string,
  startLine: number,
  endLine: number,
): string {
  const lang = getLanguage(filePath);
  const lineRange =
    startLine === endLine ? `L${startLine}` : `L${startLine}-${endLine}`;
  const fileName = filePath.split("/").pop() ?? filePath;
  return `\`${fileName}\` \`${lineRange}\`\n\`\`\`${lang}\n// ${filePath}:${lineRange}\n${code}\n\`\`\``;
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
   * Pending diffs keyed by file path.
   * When the agent modifies a file while it is open, we capture the original
   * content and the new (modified) content so the user can review.
   */
  const [pendingDiffs, setPendingDiffs] = useState<Map<string, PendingDiff>>(
    new Map(),
  );

  const activeTab = tabs.find((t) => t.path === activeTabPath) ?? null;
  const activeDiff = activeTabPath
    ? pendingDiffs.get(activeTabPath)
    : undefined;

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
    (editor: MonacoEditor.IStandaloneCodeEditor, monaco: Monaco) => {
      editorRef.current = editor;

      editor.onDidChangeCursorSelection((e) => {
        const sel = e.selection;
        setHasSelection(
          !sel.isEmpty() ||
            sel.startLineNumber !== sel.endLineNumber ||
            sel.startColumn !== sel.endColumn,
        );
      });

      // Ctrl/Cmd+C → copy with @file:Lx-y context
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | (monaco.KeyCode.KeyC as unknown as number),
        () => {
          const sel = editor.getSelection();
          if (!sel || sel.isEmpty()) {
            document.execCommand("copy");
            return;
          }
          const model = editor.getModel();
          if (!model) return;
          const code = model.getValueInRange(sel);
          const filePath = activeTabPathRef.current;
          if (!filePath) {
            navigator.clipboard.writeText(code).catch(() => undefined);
            return;
          }
          navigator.clipboard
            .writeText(
              formatSelectionForChat(
                filePath,
                code,
                sel.startLineNumber,
                sel.endLineNumber,
              ),
            )
            .catch(() => undefined);
        },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  /**
   * Register the Ctrl/Cmd+C override on the modified (right) pane of the
   * DiffEditor so copy-to-Chat context works even in diff review mode.
   */
  const handleDiffMount: DiffOnMount = useCallback(
    (diffEditor, monaco) => {
      const modifiedEditor = diffEditor.getModifiedEditor();
      modifiedEditor.addCommand(
        monaco.KeyMod.CtrlCmd | (monaco.KeyCode.KeyC as unknown as number),
        () => {
          const sel = modifiedEditor.getSelection();
          if (!sel || sel.isEmpty()) {
            document.execCommand("copy");
            return;
          }
          const model = modifiedEditor.getModel();
          if (!model) return;
          const code = model.getValueInRange(sel);
          const filePath = activeTabPathRef.current;
          if (!filePath) {
            navigator.clipboard.writeText(code).catch(() => undefined);
            return;
          }
          navigator.clipboard
            .writeText(
              formatSelectionForChat(
                filePath,
                code,
                sel.startLineNumber,
                sel.endLineNumber,
              ),
            )
            .catch(() => undefined);
        },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
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
    const code = selection.isEmpty()
      ? model.getValue()
      : model.getValueInRange(selection);
    const startLine = selection.isEmpty() ? 1 : selection.startLineNumber;
    const endLine = selection.isEmpty()
      ? model.getLineCount()
      : selection.endLineNumber;
    appendToChat(
      formatSelectionForChat(activeTabPath, code, startLine, endLine),
    );
  }, [activeTabPath]);

  // ---- Diff actions -------------------------------------------------------

  /**
   * Keep: dismiss the diff and accept the new (modified) content.
   * The file on disk is already updated; we just clear the diff state.
   */
  const handleKeep = useCallback(() => {
    const diff = pendingDiffs.get(activeTabPath);
    if (!diff) return;
    setPendingDiffs((prev) => {
      const next = new Map(prev);
      next.delete(activeTabPath);
      return next;
    });
    onTabContentChange(activeTabPath, diff.modified);
    onTabDirtyChange(activeTabPath, false);
  }, [activeTabPath, pendingDiffs, onTabContentChange, onTabDirtyChange]);

  /**
   * Undo: dismiss the diff and revert to the original content.
   * Writes the original content back to disk.
   */
  const handleUndo = useCallback(async () => {
    const diff = pendingDiffs.get(activeTabPath);
    if (!diff) return;
    setPendingDiffs((prev) => {
      const next = new Map(prev);
      next.delete(activeTabPath);
      return next;
    });
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
  }, [activeTabPath, pendingDiffs, onTabContentChange, onTabDirtyChange]);

  // ---- File-watch: show inline diff instead of silent reload ---------------

  useWorkspaceWatch((events) => {
    const path = activeTabPathRef.current;
    if (!path) return;

    const tab = tabs.find((t) => t.path === path);
    // If the user has unsaved edits, don't overwrite them
    if (tab?.dirty) return;
    // If an undo revert write is in flight, don't create a diff
    if (undoInProgressRef.current.has(path)) return;

    const affected = events.some(
      (e) =>
        e.change === "modified" &&
        e.path.replace(/\\/g, "/") === path.replace(/\\/g, "/"),
    );
    if (!affected) return;

    const existingDiff = pendingDiffs.get(path);

    workspaceApi
      .loadCodeFile(path)
      .then((res) => {
        const newModified = res.content ?? "";

        if (existingDiff) {
          // There is already a pending diff — update only the modified side so
          // the user sees the cumulative change (original → latest agent edit).
          if (newModified === existingDiff.modified) return;
          setPendingDiffs((prev) => {
            const cur = prev.get(path);
            if (!cur) return prev;
            const next = new Map(prev);
            next.set(path, { original: cur.original, modified: newModified });
            return next;
          });
        } else {
          // First edit — capture current editor content as baseline original.
          const originalContent =
            editorRef.current?.getValue() ?? tab?.content ?? "";
          if (newModified === originalContent) return;
          setPendingDiffs((prev) => {
            const next = new Map(prev);
            next.set(path, {
              original: originalContent,
              modified: newModified,
            });
            return next;
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
          const hasDiff = pendingDiffs.has(tab.path);
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
          /* Diff mode: show Keep / Undo */
          <div className={styles.diffActions}>
            <span className={styles.diffLabel}>
              <GitCompareArrows size={12} />
              Agent changed this file
            </span>
            <Tooltip title="Keep changes (accept)">
              <button
                type="button"
                className={`${styles.iconBtn} ${styles.keepBtn}`}
                onClick={handleKeep}
              >
                <Check size={13} />
                Keep
              </button>
            </Tooltip>
            <Tooltip title="Undo changes (revert to original)">
              <button
                type="button"
                className={`${styles.iconBtn} ${styles.undoBtn}`}
                onClick={() => void handleUndo()}
              >
                <RotateCcw size={13} />
                Undo
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
          ) : (
            /* ── Normal editor ──────────────────────────────────────────── */
            <Editor
              height="100%"
              path={activeTab.path}
              defaultValue={activeTab.content}
              language={getLanguage(activeTab.path)}
              theme={isDark ? "vs-dark" : "light"}
              beforeMount={handleBeforeMount}
              onMount={(editor, monaco) => handleMount(editor, monaco)}
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
