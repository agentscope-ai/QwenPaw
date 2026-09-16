import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildAuthHeaders } from "../../api/authHeaders";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import { withAgentRequestContext } from "../../api/modules/agentRequestContext";
import { personalLibraryApi } from "../../api/modules/personalLibrary";
import { workspaceApi } from "../../api/modules/workspace";
import FilePreview, { isPreviewable } from "../../pages/Coding/FilePreview";
import type { FileLocator } from "./fileLocator";
import styles from "./FilesWorkspace.module.less";

interface FilePreviewPaneProps {
  locator: FileLocator;
  requestContext: AgentRequestContext;
}

function authenticatedHeaders(context: AgentRequestContext): Record<string, string> {
  return (withAgentRequestContext(
    { headers: buildAuthHeaders() },
    context,
  )?.headers ?? {}) as Record<string, string>;
}

export function fileLocatorDownloadUrl(locator: FileLocator): string | null {
  if (!locator.stableId) return null;
  if (locator.category === "artifact") {
    return `/api/console/artifacts/${encodeURIComponent(locator.stableId)}/download`;
  }
  if (locator.category === "attachment") {
    return `/api/console/attachments/${encodeURIComponent(locator.stableId)}`;
  }
  return null;
}

export default function FilePreviewPane({ locator, requestContext }: FilePreviewPaneProps) {
  const { t } = useTranslation();
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const binaryUrl = useMemo(() => fileLocatorDownloadUrl(locator), [locator]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    setContent("");
    const load = async () => {
      if (locator.category === "memory") {
        if (!locator.memoryScope || !locator.memorySection) throw new Error("invalid_memory_locator");
        return (await workspaceApi.loadMemoryFile(locator.relativePath, locator.memorySection, locator.memoryScope, requestContext)).content;
      }
      if (locator.category === "agent_config") {
        return (await workspaceApi.loadFile(locator.relativePath, requestContext)).content;
      }
      if (locator.category === "library") {
        if (!locator.stableId) throw new Error("missing_library_id");
        return (await personalLibraryApi.readText(locator.stableId, 0, 65_536, requestContext)).content;
      }
      if (!binaryUrl) throw new Error("missing_download_url");
      const response = await fetch(binaryUrl, { headers: authenticatedHeaders(requestContext) });
      if (!response.ok) throw new Error(`${response.status}`);
      const contentType = response.headers.get("Content-Type") ?? "";
      const textFile = contentType.startsWith("text/") || /\.(?:md|mdx|txt|csv|json|ya?ml|toml|xml|html?|css|less|scss|js|jsx|ts|tsx|py|java|go|rs|sh)$/i.test(locator.relativePath);
      return textFile ? response.text() : "";
    };
    void load().then((value) => {
      if (active) setContent(value);
    }).catch(() => {
      if (active) setFailed(true);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [binaryUrl, locator, requestContext]);

  if (loading) return <div className={styles.empty}>加载中</div>;
  if (failed) return <div className={styles.empty} role="alert">{t("files.fileCenter.loadFailed")}</div>;
  if (!isPreviewable(locator.relativePath)) {
    return content ? <pre className={styles.textPreview}>{content}</pre> : <div className={styles.empty}>该文件暂不支持预览</div>;
  }
  return <FilePreview filePath={locator.relativePath} content={content} binaryUrl={binaryUrl ?? undefined} workspaceBacked={false} />;
}
