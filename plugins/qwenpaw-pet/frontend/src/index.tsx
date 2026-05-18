// React and antd are injected by the QwenPaw console host at runtime;
// vite ``external``s them so nothing here is bundled. The type-only
// import below gives ``React.useState<T>()`` and friends real generic
// signatures (erased at build time, zero runtime cost).
//
// Note: ``tsconfig.json`` sets ``"types": []`` so @types/* does not
// auto-register global namespaces. Without that, @types/react's
// ``export as namespace React`` would expose ``React`` as a global
// value and clash with the ``const React = host.React`` line below
// ("Cannot redeclare block-scoped variable 'React'").
import type * as ReactNS from "react";

const host = (window as any).QwenPaw.host;
const React: typeof ReactNS = host.React;
const antd = host.antd;
const getApiUrl: (path: string) => string = host.getApiUrl;
const getApiToken: () => string = host.getApiToken;

const { Button, Card, Space, Table, Typography, message, Modal, Checkbox } =
  antd;
// Renamed Typography.Text to AntText: ``Text`` collides with the
// global DOM ``Text`` interface from ``lib.dom.d.ts``.
const { Title, Text: AntText, Paragraph } = Typography;

type PetRow = {
  folder: string;
  manifestId?: string | null;
  id: string;
  path: string;
  displayName: string;
};

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const t = getApiToken?.();
  if (t) headers.Authorization = `Bearer ${t}`;
  return headers;
}

async function apiGet(path: string): Promise<any> {
  const res = await fetch(getApiUrl(path), { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  return res.json();
}

async function apiPost(path: string, body: object): Promise<any> {
  const res = await fetch(getApiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    throw new Error(typeof data?.detail === "string" ? data.detail : text);
  }
  return data;
}

/** Codex atlas cell size (row 0 col 0 = idle frame 1). */
const CELL_W = 192;
const CELL_H = 208;

function PetThumb({ folder }: { folder: string }) {
  const ref = React.useRef<HTMLCanvasElement | null>(null);
  const [err, setErr] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setErr(false);
    const canvas = ref.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    if (!ctx) return undefined;

    (async () => {
      try {
        const url = getApiUrl(
          `/qwenpaw-pet/pets/${encodeURIComponent(folder)}/spritesheet`,
        );
        const res = await fetch(url, { headers: authHeaders() });
        if (!res.ok || cancelled) throw new Error(String(res.status));
        const blob = await res.blob();
        const bmp = await createImageBitmap(blob);
        if (cancelled) {
          bmp.close();
          return;
        }
        const dw = 96;
        const dh = 104;
        canvas.width = dw;
        canvas.height = dh;
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, dw, dh);
        ctx.drawImage(bmp, 0, 0, CELL_W, CELL_H, 0, 0, dw, dh);
        bmp.close();
      } catch {
        if (!cancelled) setErr(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [folder]);

  if (err) {
    return React.createElement(AntText, { type: "secondary" }, "—");
  }
  return React.createElement("canvas", {
    ref,
    width: 96,
    height: 104,
    style: {
      display: "block",
      borderRadius: 8,
      border: "1px solid rgba(0,0,0,0.08)",
      background: "rgba(0,0,0,0.02)",
      imageRendering: "pixelated",
    },
  });
}

function PetControlPage() {
  const [pets, setPets] = React.useState<PetRow[]>([]);
  const [petsDir, setPetsDir] = React.useState<string>("");
  const [desktop, setDesktop] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(false);

  const [importOpen, setImportOpen] = React.useState(false);
  const [importReplace, setImportReplace] = React.useState(true);
  const [importing, setImporting] = React.useState(false);
  const [selectedFiles, setSelectedFiles] = React.useState<
    { file: File; path: string }[]
  >([]);
  const [dragOver, setDragOver] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const [petData, st] = await Promise.all([
        apiGet("/qwenpaw-pet/pets"),
        apiGet("/qwenpaw-pet/status"),
      ]);
      setPets(petData.pets || []);
      setPetsDir(petData.petsDir || "");
      setDesktop(st.desktop ?? null);
    } catch (e: any) {
      message.error(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const startDesktop = async () => {
    try {
      const r = await apiPost("/qwenpaw-pet/desktop/start", {});
      const h = r?.desktop;
      const detail = [r?.message, r?.hint].filter(Boolean).join(" ");
      if (r?.alreadyRunning && h?.ok) {
        message.success(detail || "Desktop pet is already running.");
      } else if (r?.launchAttempted === false && !h?.ok) {
        message.error(detail || "Could not start the desktop pet.");
      } else if (h?.ok) {
        message.success(detail || "Desktop pet is ready.");
      } else {
        message.warning(
          detail ||
            "Desktop may still be starting; check pet-desktop.log if needed.",
        );
      }
      await refresh();
    } catch (e: any) {
      message.error(e?.message || String(e));
    }
  };

  const openImport = () => {
    setSelectedFiles([]);
    setImportReplace(true);
    setDragOver(false);
    setImportOpen(true);
  };

  // Recursively flatten a webkit FileSystemEntry into File + relative path
  // pairs. Used to translate a dropped folder into a multipart upload
  // that mirrors the on-disk layout (so the server can locate pet.json).
  const traverseEntry = async (
    entry: any,
    prefix: string,
    out: { file: File; path: string }[],
  ): Promise<void> => {
    const currentPath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isFile) {
      const file: File = await new Promise((resolve, reject) =>
        entry.file(resolve, reject),
      );
      out.push({ file, path: currentPath });
      return;
    }
    if (!entry.isDirectory) return;
    const reader = entry.createReader();
    // readEntries returns at most ~100 entries per call; drain to empty.
    while (true) {
      const batch: any[] = await new Promise((resolve, reject) =>
        reader.readEntries(resolve, reject),
      );
      if (batch.length === 0) break;
      for (const child of batch) {
        await traverseEntry(child, currentPath, out);
      }
    }
  };

  const onDropFiles = async (e: any) => {
    e.preventDefault();
    setDragOver(false);
    if (importing) return;
    const items: DataTransferItemList | undefined = e.dataTransfer?.items;
    const fallbackFiles: FileList | undefined = e.dataTransfer?.files;
    const collected: { file: File; path: string }[] = [];
    if (items && items.length > 0) {
      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        if (it.kind !== "file") continue;
        const entry = (it as any).webkitGetAsEntry?.();
        if (entry) {
          await traverseEntry(entry, "", collected);
        } else {
          const f = it.getAsFile();
          if (f) collected.push({ file: f, path: f.name });
        }
      }
    } else if (fallbackFiles) {
      for (let i = 0; i < fallbackFiles.length; i++) {
        const f = fallbackFiles[i];
        collected.push({ file: f, path: f.name });
      }
    }
    if (collected.length === 0) {
      message.warning("Drop a folder or a .zip file.");
      return;
    }
    setSelectedFiles(collected);
  };

  const onDragOver = (e: any) => {
    e.preventDefault();
    if (!importing) setDragOver(true);
  };
  const onDragLeave = (e: any) => {
    e.preventDefault();
    setDragOver(false);
  };

  const onClickDropzone = () => {
    if (!importing) fileInputRef.current?.click();
  };

  const onPickFiles = (e: any) => {
    const list: FileList | null = e.target?.files;
    if (!list || list.length === 0) return;
    const collected: { file: File; path: string }[] = [];
    for (let i = 0; i < list.length; i++) {
      const f = list[i];
      collected.push({ file: f, path: f.name });
    }
    setSelectedFiles(collected);
    // Reset so picking the same file twice still fires onChange.
    e.target.value = "";
  };

  const submitImport = async () => {
    if (selectedFiles.length === 0) {
      message.warning("Drop a folder or choose a .zip file first.");
      return;
    }
    setImporting(true);
    try {
      const form = new FormData();
      for (const { file, path } of selectedFiles) {
        form.append("files", file, path);
      }
      form.append("replace", importReplace ? "true" : "false");
      const res = await fetch(getApiUrl("/qwenpaw-pet/import-pet-upload"), {
        method: "POST",
        headers: authHeaders(),
        body: form,
      });
      const text = await res.text();
      let data: any = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { raw: text };
      }
      if (!res.ok) {
        throw new Error(typeof data?.detail === "string" ? data.detail : text);
      }
      message.success(
        `Imported "${data.displayName || data.petId}" \u2192 ${data.path}`,
      );
      setImportOpen(false);
      setSelectedFiles([]);
      await refresh();
    } catch (e: any) {
      message.error(e?.message || String(e));
    } finally {
      setImporting(false);
    }
  };

  const switchTo = async (row: PetRow) => {
    // Desktop resolves pets/<folder>; manifest "id" may differ (e.g. goose-default vs folder goose).
    const pet_id = row.folder;
    try {
      const r = await apiPost("/qwenpaw-pet/switch-pet", { pet_id });
      if (r && r.ok === false) {
        throw new Error(r.error || r.detail || "switch failed");
      }
      message.success(`Switched to "${row.displayName}" (${pet_id})`);
      await refresh();
    } catch (e: any) {
      message.error(e?.message || String(e));
    }
  };

  const columns = [
    {
      title: "Preview",
      key: "preview",
      width: 112,
      render: (_: unknown, row: PetRow) =>
        React.createElement(PetThumb, { key: row.folder, folder: row.folder }),
    },
    { title: "Name", dataIndex: "displayName", key: "displayName" },
    { title: "Folder", dataIndex: "folder", key: "folder" },
    {
      title: "pet.json id",
      key: "manifestId",
      render: (_: unknown, row: PetRow) =>
        row.manifestId
          ? String(row.manifestId)
          : React.createElement(AntText, { type: "secondary" }, "—"),
    },
    {
      title: "Action",
      key: "act",
      render: (_: unknown, row: PetRow) =>
        React.createElement(
          Button,
          { type: "primary", size: "small", onClick: () => void switchTo(row) },
          "Switch",
        ),
    },
  ];

  return React.createElement(
    Card,
    { style: { maxWidth: 880, margin: "24px auto" } },
    React.createElement(
      Space,
      { direction: "vertical", size: "large", style: { width: "100%" } },
      [
        React.createElement(
          "div",
          { key: "h" },
          React.createElement(
            Title,
            { level: 3, style: { marginBottom: 4 } },
            "QwenPaw Pet",
          ),
          React.createElement(
            Paragraph,
            { type: "secondary", style: { marginBottom: 0 } },
            "Installed pets live under your QwenPaw working directory. Start the desktop bridge, then switch the floating pet without restarting QwenPaw.",
          ),
        ),
        React.createElement(
          Space,
          { key: "actions", wrap: true },
          React.createElement(
            Button,
            { type: "primary", onClick: startDesktop },
            "Start desktop pet",
          ),
          React.createElement(Button, { onClick: openImport }, "Import pet"),
          React.createElement(
            Button,
            { onClick: () => void refresh(), loading },
            "Refresh",
          ),
        ),
        React.createElement(
          "div",
          { key: "meta" },
          React.createElement(
            AntText,
            { type: "secondary" },
            "Pets directory: ",
          ),
          React.createElement(AntText, { code: true }, petsDir || "—"),
        ),
        React.createElement(
          "div",
          { key: "dh" },
          React.createElement(AntText, { strong: true }, "Desktop health: "),
          React.createElement(
            AntText,
            { type: desktop?.ok ? "success" : "warning" },
            desktop ? JSON.stringify(desktop) : "unknown (refresh)",
          ),
        ),
        React.createElement(Table, {
          key: "tbl",
          rowKey: "folder",
          loading,
          dataSource: pets,
          columns,
          pagination: false,
          locale: {
            emptyText: "No pets found. Run: qwenpaw-pet install-pet …",
          },
        }),
        React.createElement(
          Modal,
          {
            key: "import-modal",
            title: "Import pet",
            open: importOpen,
            onOk: () => void submitImport(),
            okText: "Import",
            okButtonProps: { loading: importing },
            cancelButtonProps: { disabled: importing },
            onCancel: () => {
              if (!importing) setImportOpen(false);
            },
            destroyOnClose: true,
          },
          React.createElement(
            Space,
            { direction: "vertical", style: { width: "100%" } },
            React.createElement(
              "div",
              {
                role: "button",
                tabIndex: 0,
                onClick: onClickDropzone,
                onDrop: onDropFiles,
                onDragOver: onDragOver,
                onDragLeave: onDragLeave,
                onKeyDown: (e: any) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onClickDropzone();
                  }
                },
                style: {
                  border: `2px dashed ${dragOver ? "#1677ff" : "#d9d9d9"}`,
                  borderRadius: 8,
                  padding: "32px 16px",
                  textAlign: "center" as const,
                  cursor: importing ? "not-allowed" : "pointer",
                  background: dragOver ? "rgba(22, 119, 255, 0.06)" : "#fafafa",
                  transition: "border-color .15s ease, background .15s ease",
                  userSelect: "none" as const,
                  color: dragOver ? "#1677ff" : undefined,
                },
              },
              // Line-art cube icon (matches the dropzone reference)
              React.createElement(
                "svg",
                {
                  width: 48,
                  height: 48,
                  viewBox: "0 0 24 24",
                  fill: "none",
                  stroke: "currentColor",
                  strokeWidth: 1.5,
                  strokeLinecap: "round" as const,
                  strokeLinejoin: "round" as const,
                  style: {
                    display: "block",
                    margin: "0 auto 12px",
                    opacity: 0.7,
                  },
                },
                React.createElement("path", {
                  d:
                    "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2" +
                    " 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0" +
                    "l7-4A2 2 0 0 0 21 16z",
                }),
                React.createElement("polyline", {
                  points: "3.27 6.96 12 12.01 20.73 6.96",
                }),
                React.createElement("line", {
                  x1: "12",
                  y1: "22.08",
                  x2: "12",
                  y2: "12",
                }),
              ),
              React.createElement(
                "div",
                {
                  style: {
                    fontSize: 16,
                    fontWeight: 600,
                    marginBottom: 4,
                  },
                },
                "Drop a folder or .zip file here",
              ),
              React.createElement(
                AntText,
                { type: "secondary" },
                "or click to choose a .zip",
              ),
            ),
            React.createElement("input", {
              ref: fileInputRef,
              type: "file",
              accept: ".zip,application/zip",
              style: { display: "none" },
              onChange: onPickFiles,
            }),
            selectedFiles.length === 0
              ? React.createElement(
                  AntText,
                  { type: "secondary", style: { fontSize: 12 } },
                  "Folder or unzipped archive must contain pet.json and " +
                    "spritesheet.webp (1536\u00d71872).",
                )
              : React.createElement(
                  AntText,
                  null,
                  selectedFiles.length === 1
                    ? `Selected: ${selectedFiles[0].path}`
                    : `Selected: ${selectedFiles.length} files (root: ` +
                        `${
                          selectedFiles[0].path.split("/")[0] ||
                          selectedFiles[0].path
                        })`,
                ),
            React.createElement(
              Checkbox,
              {
                checked: importReplace,
                onChange: (e: any) => setImportReplace(!!e.target.checked),
                disabled: importing,
              },
              "Replace if a pet with the same id already exists",
            ),
          ),
        ),
      ],
    ),
  );
}

class QwenPawPetPlugin {
  readonly id = "qwenpaw-pet";

  setup(): void {
    (window as any).QwenPaw.registerRoutes?.(this.id, [
      {
        path: "/plugin/qwenpaw-pet/pets",
        component: PetControlPage,
        label: "Pet",
        icon: "🐾",
        priority: 42,
      },
    ]);
  }
}

new QwenPawPetPlugin().setup();
