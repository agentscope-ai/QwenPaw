import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { chatApi } from "../../api/modules/chat";
import FileGlyph from "./FileGlyph";
import { parseInternalFileLink } from "./internalFileLinks";
import type { FileTarget } from "./types";
import styles from "./ResponseArtifactList.module.less";

interface ResponseArtifactListProps {
  messages: unknown;
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
const FILE_IO_TOOLS = new Set(["appendfile", "editfile", "writefile"]);
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

function contentData(
  item: Record<string, unknown>,
  index: number,
): Record<string, unknown> {
  const content = Array.isArray(item.content) ? item.content : [];
  return record(record(content[index])?.data) ?? {};
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

function extractResponseArtifacts(messages: unknown): ResponseArtifact[] {
  if (!Array.isArray(messages)) return [];

  const artifacts = new Map<string, ResponseArtifact>();
  for (const value of messages) {
    const item = record(value);
    if (!item) continue;
    const type = firstString(item, ["type"]);
    if (!TOOL_OUTPUT_TYPES.has(type)) continue;

    // mergeToolMessages uses [call content, result content] for a completed
    // tool entry. Reusing that shape keeps artifacts in sync with ResponseTool.
    const callData = contentData(item, 0);
    const resultData = contentData(item, 1);
    const state = (
      firstString(resultData, ["state", "status"]) ||
      firstString(item, ["state", "status"])
    ).toLowerCase();
    if (
      resultData.is_error === true ||
      item.is_error === true ||
      FAILED_STATES.has(state)
    ) {
      continue;
    }

    const toolName =
      firstString(callData, ["name"]) || firstString(item, ["name"]);
    if (!FILE_IO_TOOLS.has(normalizedToolName(toolName))) continue;
    const params =
      parsedRecord(callData.arguments) ??
      parsedRecord(item.params) ??
      parsedRecord(item.arguments) ??
      {};
    const path = firstString(params, ["file_path"]);
    const target = targetForPath(path);
    if (!target) continue;
    const name = path.replace(/\\/g, "/").split("/").pop() || "file";
    const id = `${target.source}:${target.path}`;
    artifacts.delete(id);
    artifacts.set(id, {
      id,
      name,
      path,
      target,
      toolName,
    });
  }
  return Array.from(artifacts.values()).reverse();
}

function artifactChange(toolName?: string): ArtifactChange {
  const normalized = normalizedToolName(toolName ?? "");
  return normalized === "writefile" ? "created" : "modified";
}

export default function ResponseArtifactList({
  messages,
}: ResponseArtifactListProps) {
  const { t } = useTranslation();
  const artifacts = extractResponseArtifacts(messages);
  const gridRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [visibleCount, setVisibleCount] = useState(2);

  useEffect(() => {
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
              <i className={styles.icon} aria-hidden="true">
                <FileGlyph name={artifact.name} size={20} />
              </i>
              <span className={styles.details}>
                <strong>{artifact.name}</strong>
                <small title={artifact.path}>{artifact.path}</small>
              </span>
              <small className={styles.status} data-change={change}>
                {t(
                  change === "created"
                    ? "files.artifactCreated"
                    : "files.artifactModified",
                )}
              </small>
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
