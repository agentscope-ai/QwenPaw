import { useCallback, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { Save, FileCode } from "lucide-react";
import { Tooltip } from "antd";
import { workspaceApi } from "../../api/modules/workspace";
import { useWorkspaceWatch } from "../../hooks/useWorkspaceWatch";
import { useTheme } from "../../contexts/ThemeContext";
import styles from "./EditorPanel.module.less";

/** Derive Monaco language id from file extension. */
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

interface EditorPanelProps {
  filePath: string;
  content: string;
  onChange?: (filePath: string) => void;
}

export default function EditorPanel({
  filePath,
  content,
  onChange,
}: EditorPanelProps) {
  const { isDark } = useTheme();
  const [value, setValue] = useState(content);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  // Track dirty state in a ref so the watch callback has the latest value
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const filePathRef = useRef(filePath);
  filePathRef.current = filePath;

  // Sync when a different file is selected
  const handleMount = useCallback(() => {
    setValue(content);
    setDirty(false);
  }, [content]);

  // When the currently-open file is modified externally and there are no
  // unsaved local edits, silently reload from the server.
  useWorkspaceWatch((events) => {
    const currentPath = filePathRef.current;
    if (!currentPath || dirtyRef.current) return;

    // Normalize separators for comparison
    const affected = events.some(
      (e) =>
        e.change === "modified" &&
        e.path.replace(/\\/g, "/") === currentPath.replace(/\\/g, "/"),
    );
    if (!affected) return;

    workspaceApi
      .loadCodeFile(currentPath)
      .then((res) => {
        setValue(res.content ?? "");
        setDirty(false);
      })
      .catch(() => undefined);
  });

  const handleChange = useCallback((v: string | undefined) => {
    setValue(v ?? "");
    setDirty(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!filePath || saving) return;
    setSaving(true);
    try {
      await workspaceApi.saveFile(filePath, value);
      setDirty(false);
      onChange?.(filePath);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }, [filePath, value, saving, onChange]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        void handleSave();
      }
    },
    [handleSave],
  );

  if (!filePath) {
    return (
      <div className={styles.empty}>
        <FileCode size={36} className={styles.emptyIcon} />
        <p className={styles.emptyText}>Select a file to view</p>
      </div>
    );
  }

  const shortPath = filePath.split("/").slice(-2).join("/");

  return (
    <div className={styles.wrap} onKeyDown={handleKeyDown}>
      <div className={styles.toolbar}>
        <span className={styles.fileName}>{shortPath}</span>
        {dirty && <span className={styles.dirtyDot} title="Unsaved changes" />}
        <div className={styles.toolbarRight}>
          <Tooltip title="Save (Cmd+S)">
            <button
              type="button"
              className={styles.saveBtn}
              onClick={handleSave}
              disabled={saving || !dirty}
            >
              <Save size={13} />
            </button>
          </Tooltip>
        </div>
      </div>
      <div className={styles.editor}>
        <Editor
          height="100%"
          path={filePath}
          defaultValue={content}
          language={getLanguage(filePath)}
          theme={isDark ? "vs-dark" : "light"}
          onMount={handleMount}
          onChange={handleChange}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: "on",
            scrollBeyondLastLine: false,
            wordWrap: "on",
            tabSize: 2,
          }}
        />
      </div>
    </div>
  );
}
