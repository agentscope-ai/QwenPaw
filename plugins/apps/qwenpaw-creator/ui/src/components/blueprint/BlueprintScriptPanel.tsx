import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { message } from "antd";
import { Film, LayoutList } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  ProjectDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import {
  selectTimelineScriptSlot,
  summarizeTimeline,
} from "@/selectors/blueprintSelectors";
import {
  orderedTimelineElements,
  selectTimelineById,
} from "@/selectors/timelineElementSelectors";
import { TONE_CHIP } from "./tones";
import EpisodeOverviewRail from "./EpisodeOverviewRail";

/* ------------------------------------------------------------------ */
/* Line-based markdown rendering (same visual as the demo BlockView).   */
/* ------------------------------------------------------------------ */

type ScriptBlock =
  | { kind: "scene"; text: string }
  | { kind: "hook"; text: string }
  | { kind: "line"; character: string; parenthetical?: string; text: string }
  | { kind: "action"; text: string };

const LINE_PATTERN = /^\*\*(.+?)\*\*\s*(?:[（(](.+?)[)）])?\s*[:：]\s*(.*)$/;

export function parseScriptMarkdown(markdown: string): ScriptBlock[] {
  const blocks: ScriptBlock[] = [];
  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (/^#{1,6}\s/.test(line)) {
      blocks.push({ kind: "scene", text: line.replace(/^#{1,6}\s+/, "") });
      continue;
    }
    if (line.startsWith(">")) {
      blocks.push({ kind: "hook", text: line.replace(/^>\s?/, "") });
      continue;
    }
    const dialogue = line.match(LINE_PATTERN);
    if (dialogue) {
      blocks.push({
        kind: "line",
        character: dialogue[1],
        parenthetical: dialogue[2],
        text: dialogue[3],
      });
      continue;
    }
    blocks.push({ kind: "action", text: line });
  }
  return blocks;
}

const MD_LINK = /\[([^\]]+)\]\(([^)\s]+)\)/g;
const MD_BOLD = /\*\*([^*]+)\*\*/g;

function renderInlineBold(text: string, keyBase: number): ReactNode[] {
  MD_BOLD.lastIndex = 0;
  if (!MD_BOLD.test(text)) return [text];
  MD_BOLD.lastIndex = 0;
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = keyBase;
  let match: RegExpExecArray | null;
  while ((match = MD_BOLD.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    nodes.push(
      <b key={`b${key++}`} className="text-[var(--color-text-primary)]">
        {match[1]}
      </b>,
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/**
 * Scripts are text-first: only real edit-genre source timecode refs render
 * as chips; any other (hallucinated) media link degrades to its label.
 * Inline **bold** renders as emphasis instead of raw asterisks.
 */
function renderScriptText(text: string): ReactNode {
  MD_LINK.lastIndex = 0;
  const hasLink = MD_LINK.test(text);
  MD_LINK.lastIndex = 0;
  if (!hasLink) return renderInlineBold(text, 0);
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  while ((match = MD_LINK.exec(text))) {
    if (match.index > last) {
      nodes.push(...renderInlineBold(text.slice(last, match.index), key));
      key += 50;
    }
    const [, label, url] = match;
    if (url.startsWith("source-version://")) {
      const params = new URLSearchParams(url.split("?")[1] ?? "");
      const tin = params.get("in");
      const tout = params.get("out");
      nodes.push(
        <span
          key={`l${key++}`}
          className="mx-0.5 inline-flex items-center gap-1 rounded bg-[var(--color-bg-secondary)] px-1.5 py-px align-baseline text-[11px] font-medium text-[var(--color-text-secondary)]"
          title={url}
        >
          <Film className="h-3 w-3 text-[var(--color-accent)]" />
          {label}
          {tin && tout && (
            <span className="tabular-nums text-[var(--color-text-tertiary)]">
              {tin}–{tout}
            </span>
          )}
        </span>,
      );
    } else {
      nodes.push(label);
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    nodes.push(...renderInlineBold(text.slice(last), key + 100));
  }
  return nodes;
}

function BlockView({ block }: { block: ScriptBlock }) {
  if (block.kind === "scene") {
    return (
      <span className="mb-1.5 mt-3.5 inline-block rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-0.5 text-[11px] font-bold tracking-wide text-[var(--color-text-secondary)] first:mt-0">
        {block.text}
      </span>
    );
  }
  if (block.kind === "line") {
    return (
      <p className="my-1 ml-8">
        <b className="mr-2 text-[var(--color-text-primary)]">
          {block.character}
        </b>
        {block.parenthetical && (
          <span className="mr-1.5 text-xs text-[var(--color-text-tertiary)]">
            （{block.parenthetical}）
          </span>
        )}
        {renderScriptText(block.text)}
      </p>
    );
  }
  if (block.kind === "hook") {
    return (
      <div className="mt-2.5 rounded-r-lg border-l-[3px] border-[var(--color-accent)] bg-[var(--color-accent-soft)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        {renderScriptText(block.text)}
      </div>
    );
  }
  return (
    <p className="my-1 text-[var(--color-text-secondary)]">
      {renderScriptText(block.text)}
    </p>
  );
}

/* ------------------------------------------------------------------ */
/* Legacy read-only mapping for projects created before scripts.        */
/* ------------------------------------------------------------------ */

function LegacyMapping({
  project,
  elements,
}: {
  project: ProjectDocument;
  elements: TimelineElementDocument[];
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <div className="rounded-r-lg border-l-[3px] border-[var(--color-border-strong)] bg-[var(--color-bg-secondary)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
        {t("blueprint.legacyScriptHint")}
      </div>
      {project.strategy.creative_brief && (
        <div>
          <span className="mb-1.5 inline-block rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-0.5 text-[11px] font-bold tracking-wide text-[var(--color-text-secondary)]">
            {t("blueprint.legacyBrief")}
          </span>
          <p className="whitespace-pre-wrap text-[var(--color-text-secondary)]">
            {project.strategy.creative_brief}
          </p>
        </div>
      )}
      {elements.map((element) => {
        const creation = element.creation;
        const intent =
          "intent" in creation && typeof creation.intent === "string"
            ? creation.intent
            : "";
        const narrative =
          "narrative" in creation && typeof creation.narrative === "string"
            ? creation.narrative
            : "";
        if (!intent && !narrative && creation.type !== "r2v") return null;
        return (
          <div key={element.element_id}>
            <span className="mb-1.5 inline-block rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-0.5 text-[11px] font-bold tracking-wide text-[var(--color-text-secondary)]">
              {element.label || element.element_id}
            </span>
            {(intent || narrative) && (
              <p className="text-[var(--color-text-secondary)]">
                {narrative || intent}
              </p>
            )}
            {creation.type === "r2v" && creation.shots.order.length > 0 && (
              <table className="mt-1.5 w-full border-collapse text-xs">
                <tbody>
                  {creation.shots.order.map((shotId) => {
                    const shot = creation.shots.items[shotId];
                    if (!shot) return null;
                    return (
                      <tr
                        key={shotId}
                        className="border-b border-dashed border-[var(--color-border)] last:border-b-0"
                      >
                        <td className="py-1 pr-2 text-[var(--color-text-tertiary)]">
                          {shot.camera || shot.framing || "—"}
                        </td>
                        <td className="py-1 text-[var(--color-text-secondary)]">
                          {shot.description}
                          {shot.dialogue ? ` · ${shot.dialogue}` : ""}
                        </td>
                        <td className="py-1 pl-2 text-right tabular-nums text-[var(--color-text-tertiary)]">
                          {shot.duration_seconds != null
                            ? `${shot.duration_seconds}s`
                            : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Panel                                                                */
/* ------------------------------------------------------------------ */

interface BlueprintScriptPanelProps {
  project: ProjectDocument;
  projectId: string;
  timelineId: string | null;
  open: boolean;
  /** 单集设计 (84:37778): render as the page's main content, not an overlay. */
  inline?: boolean;
  onClose: () => void;
  onOpenTimeline: (timelineId: string) => void;
  onOpenVisualEntity: (entityId: string) => void;
}

/**
 * Inline script review panel: overlays only the workspace column so the
 * AgentDock stays visible. Approval lives in the dock DecisionTray — this
 * panel only offers editing actions (hard rule §2).
 */
export default function BlueprintScriptPanel({
  project,
  projectId,
  timelineId,
  open,
  inline = false,
  onClose,
  onOpenTimeline,
  onOpenVisualEntity,
}: BlueprintScriptPanelProps) {
  const { t } = useTranslation();
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const timeline = selectTimelineById(project, timelineId);
  const script = useMemo(
    () => selectTimelineScriptSlot(project, timelineId),
    [project, timelineId],
  );
  const summary = useMemo(
    () =>
      timelineId
        ? summarizeTimeline(
            project,
            timelineId,
            Math.max(0, project.timelines.order.indexOf(timelineId)),
          )
        : null,
    [project, timelineId],
  );
  const elements = useMemo(
    () =>
      orderedTimelineElements(timeline).filter((element) => element.enabled),
    [timeline],
  );
  const [scriptText, setScriptText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const selectedVersionId = script?.selected?.version_id ?? null;

  useEffect(() => {
    if (!open || !selectedVersionId) {
      setScriptText(null);
      setLoadError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    fetch(getArtifactVersionMediaUrl(selectedVersionId))
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((text) => {
        if (!cancelled) setScriptText(text);
      })
      .catch((error: Error) => {
        if (!cancelled) setLoadError(error.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, selectedVersionId]);

  const [synopsisDraft, setSynopsisDraft] = useState("");
  useEffect(() => {
    setSynopsisDraft(timeline?.synopsis ?? "");
  }, [timeline?.synopsis, timelineId, open]);

  // Real users expect Escape to dismiss the inline panel.
  useEffect(() => {
    if (!open || inline) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA)$/.test(target.tagName)) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const blocks = useMemo(
    () => (scriptText ? parseScriptMarkdown(scriptText) : []),
    [scriptText],
  );

  if (!open || !timeline || !timelineId || !summary) return null;

  const title =
    timeline.title || t("blueprint.episodeN", { n: summary.index + 1 });
  const synopsisDirty = synopsisDraft !== (timeline.synopsis ?? "");

  const saveSynopsis = async () => {
    try {
      const hasField = typeof timeline.synopsis === "string";
      await patchProject(projectId, [
        {
          op: hasField ? "replace" : "add",
          path: `/timelines/items/${timelineId}/synopsis`,
          before: hasField ? timeline.synopsis : undefined,
          missingBefore: !hasField,
          value: synopsisDraft,
        },
      ]);
      message.success(t("blueprint.synopsisSaved"));
    } catch (error) {
      message.error(
        t("blueprint.synopsisSaveFailed", {
          detail: (error as Error).message,
        }),
      );
    }
  };

  const requestChanges = () => {
    // Prefill the assistant composer instead of firing a message: the
    // script rides along as a selection attachment and the user adds
    // concrete feedback before sending.
    const dock = useAgentDockUiStore.getState();
    dock.setSelection({
      text: timeline.synopsis || title,
      ref: `timeline:${timelineId}`,
      field: script?.slot.slot_id ?? null,
      start: 0,
      end: 0,
      label: t("blueprint.scriptAttachmentLabel", { title }),
      kind: "text",
    });
    dock.setDraft(t("blueprint.requestChangesDraft", { title }));
    dock.setSidebarTab("assistant");
    message.success(t("blueprint.requestChangesPrefilled"));
  };

  return (
    <div
      data-blueprint-script-panel
      className={
        inline
          ? "flex min-h-0 flex-1 flex-col bg-[var(--color-bg-layout)]"
          : "panel-enter absolute inset-0 z-30 flex min-h-0 flex-col bg-[var(--color-bg-layout)]"
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-5 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          {!inline && (
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary shrink-0"
              title={t("blueprint.closeScriptPanel")}
            >
              {t("common.back")}
            </button>
          )}
          <h3 className="truncate text-sm font-medium text-[var(--color-text-primary)]">
            {t("blueprint.scriptPanelTitle", { title })}
          </h3>
          {script?.selected ? (
            <>
              <span className="shrink-0 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 py-0.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
                {t("blueprint.scriptVersion", {
                  count: script.slot.version_ids.length,
                })}
              </span>
              {script.selected.stale && (
                <span
                  className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${TONE_CHIP.wait}`}
                >
                  {t("blueprint.scriptStaleChip")}
                </span>
              )}
            </>
          ) : (
            <span
              className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${TONE_CHIP.idle}`}
            >
              {t("blueprint.legacyChip")}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={requestChanges}
          >
            {t("blueprint.requestChanges")}
          </button>
          <span className="mx-0.5 h-[22px] w-px bg-[var(--color-border)]" />
          <button
            type="button"
            onClick={() => onOpenTimeline(timelineId)}
            className="inline-flex items-center gap-2 rounded-[10px] bg-[var(--color-text-primary)] px-5 py-2.5 text-sm font-bold leading-none text-[var(--color-bg-primary)] shadow-[0_2px_8px_rgba(0,0,0,.2)] transition-all hover:-translate-y-px hover:opacity-90 hover:shadow-[0_4px_14px_rgba(0,0,0,.25)]"
          >
            <LayoutList className="h-4 w-4" />
            {t("blueprint.enterTimeline")}
          </button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(300px,389px)]">
        <div className="min-h-0 overflow-y-auto bg-[var(--color-bg-primary)] px-8 py-5">
          <div className="mx-auto max-w-[688px] space-y-6">
            {/* 剧本摘要: the editable episode synopsis. */}
            <section className="space-y-2">
              <span className="block text-sm font-medium text-[var(--color-text-primary)]">
                {t("blueprint.scriptSummary")}
              </span>
              <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3">
                <textarea
                  value={synopsisDraft}
                  onChange={(event) => setSynopsisDraft(event.target.value)}
                  data-creator-field={`timeline:${timelineId}/synopsis`}
                  data-creator-field-label={`${title} · ${t(
                    "blueprint.synopsis",
                  )}`}
                  data-creator-path={`/timelines/items/${timelineId}/synopsis`}
                  rows={4}
                  className="w-full resize-y rounded-lg border-none bg-transparent text-sm leading-[1.6] text-[var(--color-text-primary)] outline-none"
                />
                {synopsisDirty && (
                  <button
                    type="button"
                    onClick={() => void saveSynopsis()}
                    className="btn-secondary mt-1.5 !px-2.5 !py-1 !text-[11px]"
                  >
                    {t("blueprint.saveSynopsis")}
                  </button>
                )}
              </div>
            </section>

            {/* 剧本内容: the reviewed script itself. */}
            <section className="space-y-2">
              <span className="block text-sm font-medium text-[var(--color-text-primary)]">
                {t("blueprint.scriptContent")}
              </span>
              <div
                data-creator-field={`script:${timelineId}/body`}
                data-creator-field-label={t("blueprint.scriptPanelTitle", {
                  title,
                })}
                data-creator-path={
                  script?.selected
                    ? `artifact:${script.slot.slot_id}@${script.selected.version_id}`
                    : undefined
                }
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 px-4 py-3 text-[13px] leading-[1.9] text-[var(--color-text-primary)]"
              >
                {script?.selected ? (
                  loading ? (
                    <p className="text-xs text-[var(--color-text-tertiary)]">
                      {t("blueprint.scriptLoading")}
                    </p>
                  ) : loadError ? (
                    <p className="text-xs text-[var(--color-danger,#ef4444)]">
                      {t("blueprint.scriptLoadFailed", { detail: loadError })}
                    </p>
                  ) : (
                    blocks.map((block, index) => (
                      <BlockView key={index} block={block} />
                    ))
                  )
                ) : (
                  <LegacyMapping project={project} elements={elements} />
                )}
              </div>
            </section>
          </div>
        </div>
        <EpisodeOverviewRail
          project={project}
          timelineId={timelineId}
          elements={elements}
          summary={summary}
          onOpenVisualEntity={onOpenVisualEntity}
        />
      </div>
    </div>
  );
}
