import { useState } from "react";
import { message } from "antd";
import { ClipboardCheck, Eye, PlayCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  ExecutionAuthorizationApproval,
  ExecutionAuthorizationView,
  ProjectDocument,
} from "@/contracts/creator";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import {
  creatorReferenceLabel,
  creatorToolLabel,
} from "@/lib/creatorPresentation";
import OnboardingHint from "@/components/onboarding/OnboardingHint";
import { navigateToLocator } from "@/routing/locators";
import { resolveCreatorLocator } from "@/routing/locatorTargets";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import i18n from "@/i18n";

const BUTTON_BASE =
  "rounded-md px-2 py-1 text-[11px] font-medium transition-colors disabled:opacity-50";
const BUTTON_PRIMARY = `${BUTTON_BASE} bg-[var(--color-text-primary)] text-[var(--color-bg-primary)] hover:opacity-90`;
const BUTTON_GHOST = `${BUTTON_BASE} border border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]`;

export function authorizationApprovalPayload(
  authorization: ExecutionAuthorizationView,
): ExecutionAuthorizationApproval {
  return {
    authorizationToken: authorization.authorizationToken,
    provider: authorization.provider,
    model: authorization.model,
    // Local price estimation was removed (stale price tables mislead);
    // the backend treats 0 as "no client-side cost bound".
    maxCost: 0,
    maxCandidates: authorization.maxCandidates,
  };
}

const AUTHORIZATION_OPERATIONS = new Set([
  "image_generation",
  "r2v_generation",
  "s2v_generation",
  "tts_generation",
  "create_character_voice",
]);

const CHECKPOINT_LABELS = {
  plan: "executionAuth.checkpointPlan",
  design: "executionAuth.checkpointDesign",
  structure: "executionAuth.checkpointStructure",
  script: "executionAuth.checkpointScript",
  direction: "executionAuth.checkpointDirection",
} as const;

/** Checkpoints share the approval transport, but do not consent to a model call. */
export function authorizationCheckpointPhase(
  authorization: ExecutionAuthorizationView,
): keyof typeof CHECKPOINT_LABELS | "unknown" | null {
  const operation = authorization.scope.operation;
  if (
    typeof operation !== "string" ||
    (operation !== "creation_checkpoint" &&
      !operation.startsWith("creation_checkpoint_"))
  )
    return null;
  const phase =
    operation === "creation_checkpoint"
      ? authorization.scope.checkpointPhase
      : operation.slice("creation_checkpoint_".length);
  return typeof phase === "string" &&
    Object.prototype.hasOwnProperty.call(CHECKPOINT_LABELS, phase)
    ? (phase as keyof typeof CHECKPOINT_LABELS)
    : "unknown";
}

export function authorizationOperation(
  authorization: ExecutionAuthorizationView,
): string {
  const checkpoint = authorizationCheckpointPhase(authorization);
  if (checkpoint)
    return i18n.t(
      checkpoint === "unknown"
        ? "executionAuth.checkpointConfirm"
        : CHECKPOINT_LABELS[checkpoint],
    );
  const operation = authorization.scope.operation;
  return typeof operation === "string" &&
    AUTHORIZATION_OPERATIONS.has(operation)
    ? creatorToolLabel(operation)
    : i18n.t("executionAuth.title");
}

function authorizationTarget(
  authorization: ExecutionAuthorizationView,
  project?: ProjectDocument | null,
): string {
  return creatorReferenceLabel(
    { ref: authorization.targetRef, name: "" },
    project,
  );
}

/** Model identity is meaningful for consent; free-form provider errors are not. */
export function authorizationModelLabel(
  authorization: ExecutionAuthorizationView,
): string {
  if (authorizationCheckpointPhase(authorization)) return "";
  const identifier =
    /^[A-Za-z0-9][A-Za-z0-9._-]*(?:\/[A-Za-z0-9][A-Za-z0-9._-]*){0,2}$/u;
  const identity = (value: unknown): string | null =>
    typeof value === "string" && identifier.test(value) && value.length <= 120
      ? value
      : null;
  return (
    [identity(authorization.provider), identity(authorization.model)]
      .filter(Boolean)
      .join(" / ") || i18n.t("presentation.dash")
  );
}

export function authorizationParameterSummary(
  authorization: ExecutionAuthorizationView,
): string {
  if (authorizationCheckpointPhase(authorization)) return "";
  const raw = authorization.scope.parameters;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return "";
  const parameters = raw as Record<string, unknown>;
  const parts: string[] = [];
  if (
    typeof parameters.durationSeconds === "number" &&
    Number.isFinite(parameters.durationSeconds) &&
    parameters.durationSeconds > 0
  ) {
    parts.push(
      i18n.t("executionAuth.duration", {
        duration: parameters.durationSeconds,
      }),
    );
  }
  if (
    typeof parameters.resolution === "string" &&
    /^(?:[1-9]\d{2,3}p|[1-9]k)$/iu.test(parameters.resolution)
  ) {
    parts.push(
      i18n.t("executionAuth.resolutionLabel", {
        resolution: parameters.resolution.toUpperCase(),
      }),
    );
  }
  const validRatio = (value: unknown): value is string =>
    typeof value === "string" && /^[1-9]\d{0,3}:[1-9]\d{0,3}$/u.test(value);
  if (validRatio(parameters.ratio)) {
    parts.push(i18n.t("executionAuth.ratio", { ratio: parameters.ratio }));
  }
  if (validRatio(parameters.aspectRatio)) {
    parts.push(
      i18n.t("executionAuth.frameSize", { size: parameters.aspectRatio }),
    );
  }
  if (typeof parameters.generateAudio === "boolean") {
    parts.push(
      parameters.generateAudio
        ? i18n.t("executionAuth.withAudio")
        : i18n.t("executionAuth.withoutAudio"),
    );
  }
  return parts.join(" · ");
}

export function authorizationDetail(
  authorization: ExecutionAuthorizationView,
  project?: ProjectDocument | null,
): string {
  // scope.message and summary can contain prompts, internal references and
  // provider diagnostics. Only compose copy from the supported public fields.
  return [
    authorizationOperation(authorization),
    authorizationTarget(authorization, project),
    authorizationModelLabel(authorization),
    authorizationParameterSummary(authorization),
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Jump target for a production confirmation's "查看" (view) button: locate the
 * prompt-editing spot that is about to feed generation, so users can actually
 * inspect the generation input before confirming the spend.
 */
export function authorizationJumpTarget(
  authorization: ExecutionAuthorizationView,
  project?: ProjectDocument | null,
): { locator: Record<string, string>; field?: string } | null {
  const checkpoint = authorizationCheckpointPhase(authorization);
  if (checkpoint) {
    if (checkpoint === "unknown" || checkpoint === "plan") return null;
    return {
      locator: {
        page: checkpoint === "design" ? "assets" : "blueprint",
      },
    };
  }
  const targetRef = authorization.targetRef ?? "";
  if (targetRef.startsWith("element:")) {
    const elementId = targetRef.slice("element:".length);
    const locator = resolveCreatorLocator(
      { page: "element", elementId },
      project,
    );
    const operation =
      typeof authorization.scope.operation === "string"
        ? authorization.scope.operation.toLowerCase()
        : "";
    const promptField = ["r2v_generation", "s2v_generation"].includes(operation)
      ? "video_prompt"
      : "storyboard_prompt";
    const field = locator.timelineId
      ? projectJsonPointer(
          "timelines",
          "items",
          locator.timelineId,
          "elements_by_id",
          elementId,
          "creation",
          promptField,
        )
      : undefined;
    return {
      locator: {
        ...locator,
        ...(field ? { field } : {}),
      },
      field,
    };
  }
  if (/^(?:asset|visual-entity|visual-variant):/u.test(targetRef)) {
    const locator = resolveCreatorLocator(
      { page: "assets", assetId: targetRef.slice(targetRef.indexOf(":") + 1) },
      project,
    );
    const parameters = authorization.scope.parameters;
    const variantId =
      parameters && typeof parameters === "object" && !Array.isArray(parameters)
        ? (parameters as Record<string, unknown>).variantId
        : null;
    // image_generation uses asset:<entity> plus parameters.variantId. Only
    // accept a real variant on that entity; an explicit target ref wins.
    if (!locator.variantId && typeof variantId === "string") {
      // A missing/stale target cannot safely fall back to a different active
      // variant. The next project snapshot can make this View available.
      if (
        !project?.visual.entities.items[locator.assetId]?.variants.items[
          variantId
        ]
      )
        return null;
      locator.variantId = variantId;
    }
    const field = locator.variantId
      ? projectJsonPointer(
          "visual",
          "entities",
          "items",
          locator.assetId,
          "variants",
          "items",
          locator.variantId,
          "prompt",
        )
      : undefined;
    return { locator: { ...locator, ...(field ? { field } : {}) }, field };
  }
  if (targetRef.startsWith("timeline:")) {
    return {
      locator: {
        page: "plan",
        timelineId: targetRef.slice("timeline:".length),
      },
    };
  }
  return null;
}

export default function ExecutionAuthorizationCard({
  authorization,
  project,
}: {
  authorization: ExecutionAuthorizationView;
  project?: ProjectDocument | null;
}) {
  const { t } = useTranslation();
  const approve = useExecutionAuthorizationStore((state) => state.approve);
  const decline = useExecutionAuthorizationStore((state) => state.decline);
  const projectId = useExecutionAuthorizationStore((state) => state.projectId);
  const [busy, setBusy] = useState(false);
  if (authorization.status !== "PENDING") return null;

  const parameterSummary = authorizationParameterSummary(authorization);
  const checkpoint = authorizationCheckpointPhase(authorization);
  const jumpTarget = authorizationJumpTarget(authorization, project);

  const openTarget = () => {
    if (!jumpTarget || !projectId) return;
    navigateToLocator(projectId, jumpTarget.locator, {
      review: true,
      field: jumpTarget.field,
      description: checkpoint
        ? authorizationOperation(authorization)
        : t("executionAuth.productionConfirm"),
    });
  };

  const continueRun = async () => {
    setBusy(true);
    try {
      await approve(
        authorization.id,
        authorizationApprovalPayload(authorization),
      );
      message.success(
        t(
          checkpoint
            ? "executionAuth.checkpointConfirmed"
            : "executionAuth.confirmed",
        ),
      );
    } catch {
      message.error(t("agent.executionFailed"));
    } finally {
      setBusy(false);
    }
  };
  const cancelRun = async () => {
    setBusy(true);
    try {
      await decline(authorization.id, authorization.authorizationToken);
      message.success(
        t(
          checkpoint
            ? "executionAuth.checkpointCancelled"
            : "executionAuth.cancelled",
        ),
      );
    } catch {
      message.error(t("agent.executionFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article
      data-execution-authorization-card={authorization.id}
      className="rounded-xl border border-[var(--color-warning)]/50 bg-[var(--color-warning-soft)]/40 p-2.5"
    >
      {!checkpoint && (
        <OnboardingHint hintKey="executionAuthorization" className="mb-2">
          {t("executionAuth.firstTimeDesc")}
        </OnboardingHint>
      )}
      <div className="flex items-start gap-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded bg-[var(--color-warning-soft)] px-1.5 py-0.5 text-[9px] font-bold text-[var(--color-warning)]">
              {checkpoint ? (
                <ClipboardCheck className="h-3 w-3" />
              ) : (
                <PlayCircle className="h-3 w-3" />
              )}
              {t(
                checkpoint
                  ? "executionAuth.checkpointConfirm"
                  : "executionAuth.productionConfirm",
              )}
            </span>
            <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--color-text-primary)]">
              {authorizationOperation(authorization)}
              {t("executionAuth.waitingConfirm")}
            </span>
            {jumpTarget && projectId && (
              <button
                type="button"
                onClick={openTarget}
                aria-label={t("executionAuth.view")}
                title={
                  checkpoint
                    ? authorizationOperation(authorization)
                    : t("executionAuth.jumpToPrompt")
                }
                className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
              >
                <Eye className="h-3 w-3" />
                {t("executionAuth.view")}
              </button>
            )}
          </div>
          <dl className="mt-1.5 space-y-0.5 text-[11px] leading-4">
            <div className="flex gap-1">
              <dt className="shrink-0 text-[var(--color-text-tertiary)]">
                {t("executionAuth.object")}
              </dt>
              <dd className="min-w-0 truncate text-[var(--color-text-secondary)]">
                {authorizationTarget(authorization, project)}
              </dd>
            </div>
            {!checkpoint && (
              <div className="flex gap-1">
                <dt className="shrink-0 text-[var(--color-text-tertiary)]">
                  {t("executionAuth.model")}
                </dt>
                <dd className="min-w-0 truncate text-[var(--color-text-secondary)]">
                  {authorizationModelLabel(authorization)}
                </dd>
              </div>
            )}
            {parameterSummary && (
              <div className="flex gap-1">
                <dt className="shrink-0 text-[var(--color-text-tertiary)]">
                  {t("executionAuth.parameter")}
                </dt>
                <dd className="min-w-0 text-[var(--color-text-secondary)]">
                  {parameterSummary}
                </dd>
              </div>
            )}
          </dl>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => void continueRun()}
          className={`flex-1 ${BUTTON_PRIMARY}`}
        >
          {t("executionAuth.continue")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void cancelRun()}
          className={`flex-1 ${BUTTON_GHOST}`}
        >
          {t("executionAuth.cancel")}
        </button>
      </div>
    </article>
  );
}
