import { ChevronDown, ChevronUp } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { chatApi } from "../../api/modules/chat";
import FileGlyph from "./FileGlyph";
import { parseInternalFileLink } from "./internalFileLinks";
import type { FileTarget } from "./types";
import styles from "./ResponseArtifactList.module.less";

interface ResponseArtifactListProps {
  output: unknown;
}

type ArtifactChange = "created" | "modified";
interface ResponseArtifact {
  id: string;
  name: string;
  path: string;
  target: FileTarget;
  toolName: string;
}

const MIN_FILE_WIDTH = 320;
const GRID_GAP = 8;
const FILE_IO_TOOLS = new Set([
  "appendfile",
  "edit",
  "editfile",
  "write",
  "writefile",
]);
const TOOL_CALL_TYPES = new Set([
  "tool_call",
  "plugin_call",
  "function_call",
  "mcp_call",
  "component_call",
]);
const TOOL_OUTPUT_TYPES = new Set([
  "tool_call_output",
  "plugin_call_output",
  "function_call_output",
  "mcp_call_output",
  "component_call_output",
]);
const FAILED_STATES = new Set([
  "cancelled",
  "canceled",
  "denied",
  "error",
  "failed",
  "interrupted",
  "rejected",
]);

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function parsedRecord(value: unknown): Record<string, unknown> | null {
  const direct = record(value);
  if (direct) return direct;
  if (typeof value !== "string") return null;
  try {
    return record(JSON.parse(value));
  } catch {
    return null;
  }
}

function firstString(
  value: Record<string, unknown>,
  keys: readonly string[],
): string {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
}

function contentData(item: Record<string, unknown>): Record<string, unknown> {
  const content = Array.isArray(item.content) ? item.content : [];
  return record(record(content[0])?.data) ?? {};
}

function normalizedToolName(name: string): string {
  return name.replace(/[^a-z\d]/gi, "").toLowerCase();
}

function targetForPath(path: string): FileTarget | null {
  const normalized = path.trim().replace(/\\/g, "/");
  const workspaceTarget = parseInternalFileLink(
    normalized.replace(/^(?:\.\/)+/, ""),
  );
  if (workspaceTarget) return { ...workspaceTarget, root: "project" };
  if (
    normalized.startsWith("/") ||
    normalized.startsWith("~") ||
    /^[a-z]:\//i.test(normalized)
  ) {
    return {
      source: "attachment",
      path: normalized,
      artifactUrl: chatApi.filePreviewUrl(normalized),
    };
  }
  return null;
}

function extractResponseArtifacts(output: unknown): ResponseArtifact[] {
  if (!Array.isArray(output)) return [];

  const calls: Array<{
    callId: string;
    toolName: string;
    path: string;
    inlineSuccess: boolean;
  }> = [];
  const successfulResults = new Set<string>();

  for (const value of output) {
    const item = record(value);
    if (!item) continue;
    const data = contentData(item);
    const type = firstString(item, ["type"]);
    const callId =
      firstString(data, ["call_id", "tool_call_id", "id"]) ||
      firstString(item, ["call_id", "tool_call_id", "id"]);

    if (TOOL_CALL_TYPES.has(type)) {
      const toolName =
        firstString(item, ["name"]) || firstString(data, ["name"]);
      if (!FILE_IO_TOOLS.has(normalizedToolName(toolName))) continue;
      const params =
        parsedRecord(item.params) ??
        parsedRecord(item.arguments) ??
        parsedRecord(data.arguments) ??
        {};
      const path = firstString(params, ["file_path"]);
      if (path) {
        const state = firstString(item, ["state", "status"]).toLowerCase();
        calls.push({
          callId,
          toolName,
          path,
          inlineSuccess: item.result !== undefined && !FAILED_STATES.has(state),
        });
      }
      continue;
    }

    if (TOOL_OUTPUT_TYPES.has(type)) {
      const state = (
        firstString(data, ["state", "status"]) ||
        firstString(item, ["state", "status"])
      ).toLowerCase();
      if (
        callId &&
        data.is_error !== true &&
        item.is_error !== true &&
        (state === "success" || state === "completed")
      ) {
        successfulResults.add(callId);
      }
    }
  }

  const artifacts = new Map<string, ResponseArtifact>();
  for (const call of calls) {
    if (!call.inlineSuccess && !successfulResults.has(call.callId)) continue;
    const target = targetForPath(call.path);
    if (!target) continue;
    const name = call.path.replace(/\\/g, "/").split("/").pop() || "file";
    const id = `${target.source}:${target.path}`;
    artifacts.delete(id);
    artifacts.set(id, {
      id,
      name,
      path: call.path,
      target,
      toolName: call.toolName,
    });
  }
  return Array.from(artifacts.values()).reverse();
}

function artifactChange(toolName?: string): ArtifactChange {
  const normalized = normalizedToolName(toolName ?? "");
  return normalized === "write" || normalized === "writefile"
    ? "created"
    : "modified";
}

export default function ResponseArtifactList({
  output,
}: ResponseArtifactListProps) {
  const { t } = useTranslation();
  const artifacts = extractResponseArtifacts(output);
  const gridRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [visibleCount, setVisibleCount] = useState(2);

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;

    const measure = () => {
      const width = grid.getBoundingClientRect().width || grid.clientWidth;
      const columns = Math.max(
        1,
        Math.floor((width + GRID_GAP) / (MIN_FILE_WIDTH + GRID_GAP)),
      );
      setVisibleCount(columns * 2);
    };
    measure();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [artifacts.length]);

  if (artifacts.length === 0) return null;

  const hasOverflow = artifacts.length > visibleCount;
  const hiddenCount = Math.max(0, artifacts.length - visibleCount);
  const visibleArtifacts = expanded
    ? artifacts
    : artifacts.slice(0, visibleCount);

  return (
    <div className={styles.list} data-testid="response-artifacts">
      <div ref={gridRef} className={styles.grid}>
        {visibleArtifacts.map((artifact) => {
          const change = artifactChange(artifact.toolName);
          return (
            <button
              key={artifact.id}
              type="button"
              className={styles.file}
              title={artifact.path}
              aria-label={`${artifact.name} ${artifact.path}`}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                window.dispatchEvent(
                  new CustomEvent("qwenpaw:open-file-preview", {
                    detail: {
                      target: artifact.target,
                      trigger: event.currentTarget,
                    },
                  }),
                );
              }}
            >
              <span className={styles.icon}>
                <FileGlyph name={artifact.name} size={20} />
              </span>
              <span className={styles.details}>
                <strong>{artifact.name}</strong>
                <small title={artifact.path}>{artifact.path}</small>
              </span>
              <span className={styles.status} data-change={change}>
                {t(
                  change === "created"
                    ? "files.artifactCreated"
                    : "files.artifactModified",
                )}
              </span>
            </button>
          );
        })}
      </div>
      {hasOverflow && (
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? (
            <>
              {t("files.artifactsCollapse")}
              <ChevronUp size={14} />
            </>
          ) : (
            <>
              {t("files.artifactsExpand", { count: hiddenCount })}
              <ChevronDown size={14} />
            </>
          )}
        </button>
      )}
    </div>
  );
}
