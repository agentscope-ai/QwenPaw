import { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { getAssetUnderstanding, getDocumentPageUrl } from "@/api/creator";

/** Parsed subset of the Source Intelligence index for document sources. */
interface DocumentIndexView {
  format: string;
  pageCount: number;
  summary: string;
  shots: Array<{
    id: string;
    page: number | null;
    checksum: string | null;
    description: string;
    events: string[];
  }>;
}

const DOC_PAGE_REF = /^doc-page:\/\/([0-9a-f]{64})\/(\d{1,4})$/;

function parseDocumentIndex(
  raw: Record<string, unknown>,
): DocumentIndexView | null {
  const media = raw.media as Record<string, unknown> | undefined;
  if (!media || media.mediaKind !== "document") return null;
  const document = media.document as
    | { format?: string; pageCount?: number }
    | undefined;
  const shots = Array.isArray(raw.shots) ? raw.shots : [];
  return {
    format: String(document?.format || "").toUpperCase(),
    pageCount: Number(document?.pageCount || 0),
    summary: String(raw.summary || ""),
    shots: shots.map((entry) => {
      const shot = entry as Record<string, unknown>;
      const match = DOC_PAGE_REF.exec(String(shot.keyframeRef || ""));
      return {
        id: String(shot.id || ""),
        checksum: match ? match[1] : null,
        page: match ? Number(match[2]) : null,
        description: String(shot.description || ""),
        events: Array.isArray(shot.events) ? shot.events.map(String) : [],
      };
    }),
  };
}

/**
 * Document flavor of the Source Intelligence result: format + page count
 * plus browsable per-page entries with their rendered page images.
 *
 * `intelligenceVersionId` binds the panel to the understanding of the
 * selected SourceAssetVersion; without it (version not yet analyzed) the
 * panel shows an empty state instead of another version's result.
 */
export default function DocumentUnderstanding({
  projectId,
  assetId,
  intelligenceVersionId,
}: {
  projectId: string;
  assetId: string;
  intelligenceVersionId: string | null;
}) {
  const [view, setView] = useState<DocumentIndexView | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty">("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setView(null);
    if (!intelligenceVersionId) {
      setState("empty");
      return undefined;
    }
    getAssetUnderstanding(projectId, assetId, intelligenceVersionId)
      .then((raw) => {
        if (cancelled) return;
        const parsed = parseDocumentIndex(raw);
        setView(parsed);
        setState(parsed ? "ready" : "empty");
      })
      .catch(() => {
        if (!cancelled) setState("empty");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, assetId, intelligenceVersionId]);

  if (state === "loading") {
    return (
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-tertiary)]">
        正在读取文档理解结果…
      </div>
    );
  }
  if (state === "empty" || !view) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-tertiary)]">
        该版本尚未完成素材理解；在会话中让 Agent
        阅读该文档后，这里会出现页级条目。
      </div>
    );
  }
  return (
    <div
      data-creator-module="document-understanding"
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3"
    >
      <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-[var(--color-text-secondary)]">
        <FileText className="h-3.5 w-3.5" />
        文档理解
        {view.format && (
          <span className="rounded bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--color-accent)]">
            {view.format}
          </span>
        )}
        {view.pageCount > 0 && (
          <span className="text-[10px] text-[var(--color-text-tertiary)]">
            共 {view.pageCount} 页
          </span>
        )}
      </div>
      {view.summary && (
        <p className="mb-2 line-clamp-4 whitespace-pre-wrap text-[11px] leading-4 text-[var(--color-text-secondary)]">
          {view.summary}
        </p>
      )}
      <div className="space-y-2">
        {view.shots.map((shot) => (
          <div
            key={shot.id}
            className="flex gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-2"
          >
            {shot.page !== null && shot.checksum && (
              <a
                href={getDocumentPageUrl(projectId, shot.checksum, shot.page)}
                target="_blank"
                rel="noreferrer"
                title={`打开第 ${shot.page} 页原图`}
                className="block w-24 shrink-0 overflow-hidden rounded border border-[var(--color-border)] bg-white"
              >
                <img
                  src={getDocumentPageUrl(projectId, shot.checksum, shot.page)}
                  alt={`第 ${shot.page} 页`}
                  className="h-full w-full object-contain"
                  loading="lazy"
                />
              </a>
            )}
            <div className="min-w-0 flex-1">
              <div className="text-[10px] font-semibold text-[var(--color-text-tertiary)]">
                {shot.page !== null ? `第 ${shot.page} 页` : "全文"}
              </div>
              <p className="mt-0.5 text-[11px] leading-4 text-[var(--color-text-secondary)]">
                {shot.description}
              </p>
              {shot.events.length > 0 && (
                <ul className="mt-1 list-inside list-disc text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                  {shot.events.slice(0, 4).map((event) => (
                    <li key={event} className="truncate">
                      {event}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
