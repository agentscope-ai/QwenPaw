import { message } from "antd";
import { artifactsApi } from "../../api/modules/artifacts";
import { artifactIdFromDownloadUrl } from "../../features/files-workspace/fileLocator";

export { artifactIdFromDownloadUrl } from "../../features/files-workspace/fileLocator";

interface LinkClick {
  target: EventTarget | null;
  preventDefault(): void;
  stopPropagation(): void;
}

export function handleArtifactDownloadLink(event: LinkClick): boolean {
  if (!(event.target instanceof Element)) return false;
  const anchor = event.target.closest<HTMLAnchorElement>("a[href]");
  if (!anchor) return false;
  const artifactId = artifactIdFromDownloadUrl(anchor.href);
  if (!artifactId) return false;
  event.preventDefault();
  event.stopPropagation();
  void artifactsApi.download(artifactId, anchor.download || "artifact")
    .catch(() => message.error("下载产物失败，请检查登录状态或重试"));
  return true;
}
