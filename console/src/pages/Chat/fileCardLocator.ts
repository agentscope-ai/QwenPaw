import { artifactIdFromDownloadUrl, type FileLocator } from "../../features/files-workspace/fileLocator";

interface FileCard {
  name?: string;
  url?: string;
}

interface ArtifactLocatorInput {
  agentId: string;
  conversationId?: string | null;
  file: FileCard;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function artifactLocatorFromFileCard({ agentId, conversationId, file }: ArtifactLocatorInput): FileLocator | null {
  if (!file.url) return null;
  const artifactId = artifactIdFromDownloadUrl(file.url);
  if (!artifactId) return null;
  const fallbackName = file.url.split("?")[0].split("/").pop() || "artifact";
  return {
    category: "artifact",
    agentId,
    stableId: artifactId,
    relativePath: file.name || fallbackName,
    ...(conversationId && UUID_PATTERN.test(conversationId) ? { conversationId } : {}),
  };
}
