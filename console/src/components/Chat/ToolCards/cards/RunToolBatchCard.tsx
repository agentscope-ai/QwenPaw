import React from "react";
import { useTranslation } from "react-i18next";
import { NodeIndexOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock, MediaPreview } from "../shared";
import {
  shortFileName,
  stringifyResult,
  toDisplayUrl,
  getFileExtFromPath,
} from "../shared/utils";
import type { DefaultBlockProps } from "../shared";

const LARGE_OUTPUT_THRESHOLD = 12000;

type MediaType = "image" | "video" | "audio" | "file";

interface MediaInfo {
  url: string;
  name: string;
  type: MediaType;
}

function classifyMediaType(ext: string): MediaType {
  if (["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"].includes(ext)) {
    return "image";
  }
  if (["mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"].includes(ext)) {
    return "video";
  }
  if (["mp3", "wav", "flac", "ape", "aac", "ogg", "wma"].includes(ext)) {
    return "audio";
  }
  return "file";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function getWorkflowLabel(params: Record<string, unknown>): string {
  const filePath = (params.file_path as string) || "";
  if (filePath) return shortFileName(filePath);
  return "workflow";
}

function getActionCount(params: Record<string, unknown>): number {
  const actions = params.actions;
  return Array.isArray(actions) ? actions.length : 0;
}

function collectRawBlocks(value: unknown, acc: unknown[] = []): unknown[] {
  if (Array.isArray(value)) {
    for (const item of value) {
      collectRawBlocks(item, acc);
    }
    return acc;
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (
      (trimmed.startsWith("[") && trimmed.endsWith("]")) ||
      (trimmed.startsWith("{") && trimmed.endsWith("}"))
    ) {
      try {
        const parsed = JSON.parse(trimmed);
        collectRawBlocks(parsed, acc);
      } catch {
        // ignore non-json string
      }
    }
    return acc;
  }

  const record = asRecord(value);
  if (!record) return acc;

  const recordType = typeof record.type === "string" ? record.type : "";
  const hasFileLikeSource =
    typeof record.filename === "string" ||
    typeof record.file_name === "string" ||
    typeof record.file_path === "string" ||
    typeof record.path === "string" ||
    typeof record.url === "string" ||
    typeof record.uri === "string" ||
    record.source != null;

  if (
    recordType === "file" ||
    recordType === "image" ||
    recordType === "audio" ||
    recordType === "video" ||
    recordType === "data" ||
    (hasFileLikeSource &&
      (recordType === "tool_result" || recordType === "tool_use"))
  ) {
    acc.push(record);
  }

  // Collect from step-level "files" array (batch step results)
  if (Array.isArray(record.files)) {
    for (const f of record.files) {
      const fileRecord = asRecord(f);
      if (fileRecord && typeof fileRecord.url === "string") {
        acc.push({ type: "file", ...fileRecord });
      }
    }
  }

  if (Array.isArray(record._raw_blocks)) {
    for (const item of record._raw_blocks) {
      collectRawBlocks(item, acc);
    }
  }

  const visited = new Set<string>();
  for (const nestedKey of [
    "content",
    "contents",
    "result",
    "results",
    "data",
    "payload",
    "artifact",
    "artifacts",
    "attachments",
    "files",
    "items",
    "message",
    "messages",
    "output",
    "outputs",
    "value",
    "source",
  ]) {
    if (nestedKey in record) {
      visited.add(nestedKey);
      collectRawBlocks(record[nestedKey], acc);
    }
  }

  if (typeof record.text === "string") {
    visited.add("text");
    collectRawBlocks(record.text, acc);
  }

  for (const [key, nestedValue] of Object.entries(record)) {
    if (!visited.has(key) && nestedValue && typeof nestedValue === "object") {
      collectRawBlocks(nestedValue, acc);
    }
  }

  return acc;
}

function collectTextBlocks(value: unknown, acc: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) {
      collectTextBlocks(item, acc);
    }
    return acc;
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (
      (trimmed.startsWith("[") && trimmed.endsWith("]")) ||
      (trimmed.startsWith("{") && trimmed.endsWith("}"))
    ) {
      try {
        const parsed = JSON.parse(trimmed);
        collectTextBlocks(parsed, acc);
      } catch {
        // ignore non-json string
      }
    }
    return acc;
  }

  const record = asRecord(value);
  if (!record) return acc;

  if (record.type === "text" && typeof record.text === "string") {
    acc.push(record.text);
    return acc;
  }

  if (Array.isArray(record._raw_blocks)) {
    for (const item of record._raw_blocks) {
      collectTextBlocks(item, acc);
    }
  }

  for (const nestedKey of [
    "content",
    "contents",
    "result",
    "results",
    "data",
    "payload",
    "artifact",
    "artifacts",
    "attachments",
    "items",
    "message",
    "messages",
    "output",
    "outputs",
    "value",
  ]) {
    if (nestedKey in record) {
      collectTextBlocks(record[nestedKey], acc);
    }
  }

  return acc;
}

function extractMediaFromBlocks(result: unknown): MediaInfo[] {
  const blocks = collectRawBlocks(result);
  const media: MediaInfo[] = [];
  const seen = new Set<string>();

  for (const block of blocks) {
    const item = asRecord(block);
    if (!item) continue;
    const sourceValue = item.source;
    const source = asRecord(sourceValue);
    const mediaTypeRaw = typeof item.type === "string" ? item.type : "file";
    const rawUrl =
      (typeof item.file_url === "string" && item.file_url) ||
      (typeof item.image_url === "string" && item.image_url) ||
      (typeof item.video_url === "string" && item.video_url) ||
      (typeof item.audio_url === "string" && item.audio_url) ||
      (typeof item.url === "string" && item.url) ||
      (typeof item.uri === "string" && item.uri) ||
      (typeof item.path === "string" && item.path) ||
      (typeof item.file_path === "string" && item.file_path) ||
      (typeof item.data === "string" && item.data) ||
      (typeof source?.url === "string" && source.url) ||
      (typeof source?.data === "string" && source.data) ||
      (typeof sourceValue === "string" && sourceValue) ||
      "";
    if (!rawUrl) continue;

    const name =
      (typeof item.filename === "string" && item.filename) ||
      (typeof item.file_name === "string" && item.file_name) ||
      (typeof item.name === "string" && item.name) ||
      (typeof item.title === "string" && item.title) ||
      shortFileName(rawUrl);
    const ext = getFileExtFromPath(rawUrl);
    const type =
      mediaTypeRaw === "image" ||
      mediaTypeRaw === "video" ||
      mediaTypeRaw === "audio"
        ? mediaTypeRaw
        : classifyMediaType(ext);
    const url = toDisplayUrl(rawUrl);
    const dedupeKey = `${type}:${name}:${url}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    media.push({
      url,
      name,
      type,
    });
  }

  return media;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripPreviewedMediaJson(
  outputText: string,
  mediaItems: MediaInfo[],
): string {
  let next = outputText;

  for (const media of mediaItems) {
    const escapedName = escapeRegExp(media.name);
    const escapedUrl = escapeRegExp(media.url);
    const patterns = [
      new RegExp(
        `\\{[\\s\\S]*?\"type\"\\s*:\\s*\"${escapeRegExp(
          media.type,
        )}\"[\\s\\S]*?(?:\"filename\"|\"file_name\"|\"name\"|\"title\")\\s*:\\s*\"${escapedName}\"[\\s\\S]*?(?:\"url\"|\"uri\"|\"path\"|\"file_path\"|\"data\")\\s*:\\s*\"${escapedUrl}\"[\\s\\S]*?\\}`,
        "g",
      ),
      new RegExp(
        `\\{[\\s\\S]*?(?:\"filename\"|\"file_name\"|\"name\"|\"title\")\\s*:\\s*\"${escapedName}\"[\\s\\S]*?(?:\"url\"|\"uri\"|\"path\"|\"file_path\"|\"data\")\\s*:\\s*\"${escapedUrl}\"[\\s\\S]*?\\}`,
        "g",
      ),
      new RegExp(
        `\\{[\\s\\S]*?(?:\"url\"|\"uri\"|\"path\"|\"file_path\"|\"data\")\\s*:\\s*\"${escapedUrl}\"[\\s\\S]*?\\}`,
        "g",
      ),
    ];

    for (const pattern of patterns) {
      next = next.replace(pattern, "");
    }
  }

  next = next
    .replace(/\n\s*\n\s*\n+/g, "\n\n")
    .replace(/\[\s*,/g, "[")
    .replace(/,\s*]/g, "]")
    .replace(/\{\s*,/g, "{")
    .replace(/,\s*}/g, "}")
    .trim();

  return next;
}

function getOutputText(result: unknown, mediaItems: MediaInfo[]): string {
  const textBlocks = collectTextBlocks(result);
  if (textBlocks.length > 0) {
    return textBlocks.join("\n");
  }

  const rawOutputText = stringifyResult(result);
  return mediaItems.length > 0
    ? stripPreviewedMediaJson(rawOutputText, mediaItems)
    : rawOutputText;
}

export interface RunToolBatchCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const RunToolBatchCard: React.FC<RunToolBatchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const workflowLabel = getWorkflowLabel(params);
  const actionCount = getActionCount(params);
  const mediaItems = extractMediaFromBlocks(content.result);
  const outputText = getOutputText(content.result, mediaItems);
  const shouldShowOutput = Boolean(outputText.trim());
  const outputBlockProps: Partial<DefaultBlockProps> =
    outputText.length > LARGE_OUTPUT_THRESHOLD ? { copyTitle: outputText } : {};

  const title = t("tool.runToolBatch", { workflow: workflowLabel });
  const inlineResult =
    content.status === "calling"
      ? actionCount > 0
        ? t("tool.runToolBatchProgress", { count: actionCount })
        : t("tool.runToolBatchRunning")
      : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<NodeIndexOutlined />}
      title={title}
      inlineResult={inlineResult}
    >
      {content.status === "calling" && (
        <DefaultBlock
          title="Workflow"
          content={t("tool.runToolBatchRunning")}
        />
      )}
      {actionCount > 0 && (
        <DefaultBlock
          title="Steps"
          content={t("tool.runToolBatchStepCount", { count: actionCount })}
        />
      )}
      {mediaItems.map((media) => (
        <MediaPreview key={`${media.name}:${media.url}`} media={media} />
      ))}
      {shouldShowOutput && (
        <DefaultBlock
          title="Output"
          content={outputText}
          {...outputBlockProps}
        />
      )}
    </ToolCardShell>
  );
};

export default RunToolBatchCard;
