import { useEffect, useRef, useState } from "react";
import { request } from "../../api/request";
import { useAgentStore } from "../../stores/agentStore";
import { getAgentAccessScopeKey } from "../../stores/chatSessionScope";
import { runtimePath, type PluginNode } from "./protocol";

type FileNode = Exclude<PluginNode, string | null>;
const MAX_BYTES = 256 * 1024 * 1024;

async function readFile(response: Response): Promise<Blob> {
  if (Number(response.headers.get("Content-Length")) > MAX_BYTES)
    throw new Error("file_too_large");
  const reader = response.body?.getReader();
  if (!reader) throw new Error("file_unavailable");
  const chunks: ArrayBuffer[] = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) {
        await reader.cancel();
        throw new Error("file_too_large");
      }
      chunks.push(value.slice().buffer);
    }
  } finally {
    reader.releaseLock();
  }
  return new Blob(chunks, { type: response.headers.get("Content-Type") || "" });
}

/** The host owns file bytes and credentials. The worker sees the completed action only. */
export function PluginFileAction({
  node,
  pluginId,
  afterUpload,
}: {
  node: FileNode;
  pluginId: string;
  afterUpload: () => void;
}) {
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [media, setMedia] = useState<{ url: string; kind: string }>();
  const path = runtimePath(pluginId, node.path);
  const scope = getAgentAccessScopeKey();
  useEffect(() => () => controller.current?.abort(), [scope, path]);
  useEffect(
    () => () => {
      if (media) URL.revokeObjectURL(media.url);
    },
    [media],
  );
  async function run(files?: File[]) {
    controller.current?.abort();
    const operation = new AbortController();
    controller.current = operation;
    const current = () =>
      !operation.signal.aborted && scope === getAgentAccessScopeKey();
    setBusy(true);
    setNotice("");
    const headers = {
      "X-Agent-Id": useAgentStore.getState().selectedAgent,
      "Idempotency-Key": crypto.randomUUID(),
    };
    const options = {
      headers,
      signal: operation.signal,
      timeout: 120000,
      redirect: "error" as const,
    };
    try {
      if (files) {
        if (
          !files.length ||
          files.length > 30 ||
          files.reduce((n, f) => n + f.size, 0) > MAX_BYTES
        )
          throw new Error("file_too_large");
        const form = new FormData();
        for (const file of files)
          form.append(node.mode === "upload-files" ? "files" : "file", file);
        form.append("clientRequestId", headers["Idempotency-Key"]);
        form.append("replace", "false");
        await request(path, { ...options, method: "POST", body: form });
        if (current()) {
          setNotice("文件已上传");
          afterUpload();
        }
      } else {
        const blob = await request<Blob>(path, {
          ...options,
          readResponse: readFile,
        });
        if (!current()) return;
        if (node.mode === "preview") {
          const mime = blob.type.split(";")[0];
          if (
            !/^(image\/(png|jpe?g|webp|gif|avif)|video\/(mp4|webm|ogg)|audio\/(mpeg|wav|x-wav|ogg|webm|mp4))$/.test(
              mime,
            )
          )
            throw new Error("unsupported_preview");
          setMedia({
            url: URL.createObjectURL(blob),
            kind: mime.split("/")[0],
          });
        } else {
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = node.filename || "download";
          anchor.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
      }
    } catch (error) {
      if (current())
        setNotice(
          error instanceof Error && error.message === "file_too_large"
            ? "文件超出 256 MiB 限制"
            : "文件操作未完成，请检查权限和文件格式。",
        );
    } finally {
      if (current()) setBusy(false);
    }
  }
  const upload = node.mode === "upload" || node.mode === "upload-files";
  return (
    <div>
      {upload ? (
        <label>
          {node.text}
          <input
            type="file"
            multiple={node.mode === "upload-files"}
            disabled={busy}
            onChange={(event) => {
              const files = Array.from(event.target.files || []);
              event.target.value = "";
              if (files.length) void run(files);
            }}
          />
        </label>
      ) : (
        <button type="button" disabled={busy} onClick={() => void run()}>
          {node.text}
        </button>
      )}
      {busy && <span role="status">正在传输…</span>}
      {notice && <span role="status">{notice}</span>}
      {media?.kind === "image" && (
        <img src={media.url} alt={node.text} style={{ maxWidth: "100%" }} />
      )}
      {media?.kind === "video" && (
        <video src={media.url} controls style={{ maxWidth: "100%" }} />
      )}
      {media?.kind === "audio" && <audio src={media.url} controls />}
    </div>
  );
}
