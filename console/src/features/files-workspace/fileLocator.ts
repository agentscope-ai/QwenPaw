export type FileCategory =
  | "attachment"
  | "library"
  | "artifact"
  | "agent_config"
  | "memory";

export interface FileLocator {
  category: FileCategory;
  agentId: string;
  stableId?: string;
  relativePath: string;
  conversationId?: string;
  memoryScope?: "public" | "private";
  memorySection?: "daily" | "digest";
}

const FILE_CATEGORIES = new Set<FileCategory>([
  "attachment",
  "library",
  "artifact",
  "agent_config",
  "memory",
]);
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ARTIFACT_DOWNLOAD_PATTERN =
  /^\/api\/console\/artifacts\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/download$/i;

function appBaseUrl(): string {
  return typeof window === "undefined"
    ? "http://localhost/"
    : window.location.href;
}

function isSafeRelativePath(value: string): boolean {
  if (!value || value !== value.trim()) return false;
  if (value.startsWith("/") || value.includes("\\")) return false;
  if (/^[a-z]:/i.test(value)) return false;
  const segments = value.split("/");
  return segments.every(
    (segment) => segment.length > 0 && segment !== "." && segment !== "..",
  );
}

function isValidLocator(locator: FileLocator): boolean {
  if (!FILE_CATEGORIES.has(locator.category)) return false;
  if (!locator.agentId.trim() || !isSafeRelativePath(locator.relativePath)) {
    return false;
  }
  if (locator.category === "artifact") {
    if (!locator.stableId || !UUID_PATTERN.test(locator.stableId)) return false;
  }
  if (locator.category === "memory") {
    if (
      !locator.memoryScope ||
      !["public", "private"].includes(locator.memoryScope) ||
      !locator.memorySection ||
      !["daily", "digest"].includes(locator.memorySection)
    ) {
      return false;
    }
  }
  if (locator.conversationId && !UUID_PATTERN.test(locator.conversationId)) {
    return false;
  }
  return true;
}

export function buildFileCenterPath(locator: FileLocator): string {
  if (!isValidLocator(locator)) {
    throw new Error("invalid_file_locator");
  }
  const params = new URLSearchParams({
    agentId: locator.agentId,
    category: locator.category,
    item: locator.relativePath,
  });
  if (locator.stableId) params.set("stableId", locator.stableId);
  if (locator.conversationId) {
    params.set("conversationId", locator.conversationId);
  }
  if (locator.memoryScope) params.set("memoryScope", locator.memoryScope);
  if (locator.memorySection) {
    params.set("memorySection", locator.memorySection);
  }
  return `/files?${params.toString()}`;
}

export function parseFileCenterLocation(rawLocation: string): FileLocator | null {
  let url: URL;
  try {
    url = new URL(rawLocation, appBaseUrl());
  } catch {
    return null;
  }
  const category = url.searchParams.get("category") as FileCategory | null;
  const agentId = url.searchParams.get("agentId") ?? "";
  const relativePath = url.searchParams.get("item") ?? "";
  if (!category || !FILE_CATEGORIES.has(category)) return null;

  const locator: FileLocator = {
    category,
    agentId,
    relativePath,
  };
  const stableId = url.searchParams.get("stableId");
  const conversationId = url.searchParams.get("conversationId");
  const memoryScope = url.searchParams.get("memoryScope");
  const memorySection = url.searchParams.get("memorySection");
  if (stableId) locator.stableId = stableId;
  if (conversationId) locator.conversationId = conversationId;
  if (memoryScope === "public" || memoryScope === "private") {
    locator.memoryScope = memoryScope;
  } else if (memoryScope) {
    return null;
  }
  if (memorySection === "daily" || memorySection === "digest") {
    locator.memorySection = memorySection;
  } else if (memorySection) {
    return null;
  }
  return isValidLocator(locator) ? locator : null;
}

export function artifactIdFromDownloadUrl(rawUrl: string): string | null {
  let url: URL;
  let base: URL;
  try {
    base = new URL(appBaseUrl());
    url = new URL(rawUrl, base);
  } catch {
    return null;
  }
  if (url.origin !== base.origin) return null;
  return ARTIFACT_DOWNLOAD_PATTERN.exec(url.pathname)?.[1] ?? null;
}
