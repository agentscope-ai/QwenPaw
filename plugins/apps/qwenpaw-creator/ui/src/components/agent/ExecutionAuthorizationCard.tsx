import { useState } from "react";
import { message } from "antd";
import { Coins, Eye, PlayCircle } from "lucide-react";
import type {
  ExecutionAuthorizationApproval,
  ExecutionAuthorizationView,
  ProjectDocument,
} from "@/contracts/creator";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { creatorTargetLabel, taskKindLabel } from "@/lib/creatorPresentation";
import OnboardingHint from "@/components/onboarding/OnboardingHint";
import { navigateToLocator } from "@/routing/locators";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";

const BUTTON_BASE =
  "rounded-md px-2 py-1 text-[11px] font-medium transition-colors disabled:opacity-50";
const BUTTON_PRIMARY = `${BUTTON_BASE} bg-[var(--color-accent)] text-white hover:opacity-90`;
const BUTTON_GHOST = `${BUTTON_BASE} border border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]`;

export interface AuthorizationBilling {
  estimatedCost?: number | null;
  currency?: string;
  displayText?: string;
  unitPrice?: string;
  formula?: string;
  pricingModel?: string;
  pricingSource?: string;
  approximate?: boolean;
  notes?: string[];
}

export function authorizationApprovalPayload(
  authorization: ExecutionAuthorizationView,
): ExecutionAuthorizationApproval {
  return {
    authorizationToken: authorization.authorizationToken,
    provider: authorization.provider,
    model: authorization.model,
    maxCost: authorization.estimatedCost ?? 0,
    maxCandidates: authorization.maxCandidates,
  };
}

export function authorizationBilling(
  authorization: ExecutionAuthorizationView,
): AuthorizationBilling | null {
  const billing = authorization.scope.billing;
  if (!billing || typeof billing !== "object") return null;
  return billing as AuthorizationBilling;
}

function authorizationOperation(
  authorization: ExecutionAuthorizationView,
): string {
  return typeof authorization.scope.operation === "string"
    ? taskKindLabel(authorization.scope.operation)
    : "高成本媒体执行";
}

function authorizationParameterSummary(
  authorization: ExecutionAuthorizationView,
): string {
  const raw = authorization.scope.parameters;
  if (!raw || typeof raw !== "object") return "";
  const parameters = raw as Record<string, unknown>;
  const parts: string[] = [];
  if (parameters.durationSeconds) {
    parts.push(`时长 ${parameters.durationSeconds}秒`);
  }
  if (typeof parameters.resolution === "string") {
    parts.push(`分辨率 ${parameters.resolution.toUpperCase()}`);
  }
  if (typeof parameters.ratio === "string") {
    parts.push(`比例 ${parameters.ratio}`);
  }
  if (typeof parameters.aspectRatio === "string") {
    parts.push(`画幅 ${parameters.aspectRatio}`);
  }
  if (typeof parameters.generateAudio === "boolean") {
    parts.push(parameters.generateAudio ? "有声" : "无声");
  }
  return parts.join(" · ");
}

/** Replace ref tokens in backend copy (asset:char:fox / element:xxx etc.) with real names. */
function humanizeRefTokens(
  text: string,
  project?: ProjectDocument | null,
): string {
  return text.replace(
    /(?:visual-entity|artifact-version|asset-version|element|asset|source):[\w.-]+(?::[\w.-]+)*/g,
    (token) => {
      const label = creatorTargetLabel(token, project);
      return label && label !== "当前项目" ? `「${label}」` : token;
    },
  );
}

export function authorizationDetail(
  authorization: ExecutionAuthorizationView,
  project?: ProjectDocument | null,
): string {
  const messageText = authorization.scope.message;
  if (typeof messageText === "string" && messageText.trim())
    return humanizeRefTokens(messageText, project);
  const detail = `${authorizationOperation(
    authorization,
  )} · ${creatorTargetLabel(authorization.targetRef, project)} · ${
    authorization.provider
  }/${authorization.model}`;
  const billing = authorizationBilling(authorization);
  return billing?.displayText
    ? `${detail} · 预计费用 ${billing.displayText}`
    : detail;
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
  const targetRef = authorization.targetRef ?? "";
  if (targetRef.startsWith("element:")) {
    const elementId = targetRef.slice("element:".length);
    const timeline = selectPrimaryTimeline(project ?? null);
    const operation =
      typeof authorization.scope.operation === "string"
        ? authorization.scope.operation.toLowerCase()
        : "";
    const promptField = operation.includes("video")
      ? "video_prompt"
      : "storyboard_prompt";
    const field = timeline
      ? `/timelines/items/${timeline.timeline_id}/elements_by_id/${elementId}/creation/${promptField}`
      : undefined;
    return {
      locator: {
        page: "element",
        elementId,
        ...(field ? { field } : {}),
      },
      field,
    };
  }
  if (targetRef.startsWith("asset:")) {
    return {
      locator: { page: "assets", assetId: targetRef.slice("asset:".length) },
    };
  }
  if (targetRef.startsWith("visual-entity:")) {
    return {
      locator: {
        page: "assets",
        assetId: targetRef.slice("visual-entity:".length),
      },
    };
  }
  if (targetRef.startsWith("timeline:")) {
    return { locator: { page: "plan" } };
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
  const approve = useExecutionAuthorizationStore((state) => state.approve);
  const decline = useExecutionAuthorizationStore((state) => state.decline);
  const projectId = useExecutionAuthorizationStore((state) => state.projectId);
  const [busy, setBusy] = useState(false);
  if (authorization.status !== "PENDING") return null;

  const billing = authorizationBilling(authorization);
  const parameterSummary = authorizationParameterSummary(authorization);
  const jumpTarget = authorizationJumpTarget(authorization, project);

  const openTarget = () => {
    if (!jumpTarget || !projectId) return;
    navigateToLocator(projectId, jumpTarget.locator, {
      review: true,
      field: jumpTarget.field,
      description: "生产确认 / 查看生成输入",
    });
  };

  const continueRun = async () => {
    setBusy(true);
    try {
      await approve(
        authorization.id,
        authorizationApprovalPayload(authorization),
      );
      message.success("已确认，专业制作将继续");
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const cancelRun = async () => {
    setBusy(true);
    try {
      await decline(authorization.id, authorization.authorizationToken);
      message.success("已取消，当前制作已终止");
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article
      data-execution-authorization-card={authorization.id}
      className="rounded-xl border border-[var(--color-warning)]/50 bg-[var(--color-warning-soft)]/40 p-2.5"
    >
      <OnboardingHint hintKey="executionAuthorization" className="mb-2">
        首次说明：Agent
        即将调用付费生成模型，下方已给出预估费用。点击「继续」才会真正执行，「取消」则终止本次制作；可在模型配置中关闭此确认。
      </OnboardingHint>
      <div className="flex items-start gap-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded bg-[var(--color-warning-soft)] px-1.5 py-0.5 text-[9px] font-bold text-[var(--color-warning)]">
              <PlayCircle className="h-3 w-3" />
              生产确认
            </span>
            <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--color-text-primary)]">
              {authorizationOperation(authorization)}等待确认
            </span>
            {jumpTarget && projectId && (
              <button
                type="button"
                onClick={openTarget}
                aria-label="查看生成输入"
                title="跳转到将要生成的 Prompt / 编辑位置，确认前先检查输入"
                className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
              >
                <Eye className="h-3 w-3" />
                查看
              </button>
            )}
          </div>
          <dl className="mt-1.5 space-y-0.5 text-[11px] leading-4">
            <div className="flex gap-1">
              <dt className="shrink-0 text-[var(--color-text-tertiary)]">
                对象
              </dt>
              <dd className="min-w-0 truncate text-[var(--color-text-secondary)]">
                {creatorTargetLabel(authorization.targetRef, project)}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="shrink-0 text-[var(--color-text-tertiary)]">
                模型
              </dt>
              <dd className="min-w-0 truncate text-[var(--color-text-secondary)]">
                {authorization.provider} / {authorization.model}
              </dd>
            </div>
            {parameterSummary && (
              <div className="flex gap-1">
                <dt className="shrink-0 text-[var(--color-text-tertiary)]">
                  参数
                </dt>
                <dd className="min-w-0 text-[var(--color-text-secondary)]">
                  {parameterSummary}
                </dd>
              </div>
            )}
          </dl>
          {billing ? (
            <div className="mt-1.5 rounded-md border border-[var(--color-warning)]/30 bg-[var(--color-bg-primary)]/60 px-2 py-1.5">
              <p className="flex items-center gap-1 text-[11px] font-semibold leading-4 text-[var(--color-warning)]">
                <Coins className="h-3 w-3" />
                预计费用 {billing.displayText ?? "费用未知"}
              </p>
              {billing.formula && (
                <p className="mt-0.5 text-[10px] leading-4 text-[var(--color-text-secondary)]">
                  计算：{billing.formula}
                  {billing.pricingModel
                    ? `（按 ${billing.pricingModel} 计价）`
                    : ""}
                </p>
              )}
              {(billing.notes ?? []).map((note) => (
                <p
                  key={note}
                  className="text-[10px] leading-4 text-[var(--color-text-tertiary)]"
                >
                  {note}
                </p>
              ))}
            </div>
          ) : (
            <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-[var(--color-text-tertiary)]">
              {authorizationDetail(authorization, project)}
            </p>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => void continueRun()}
          className={`flex-1 ${BUTTON_PRIMARY}`}
        >
          继续
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void cancelRun()}
          className={`flex-1 ${BUTTON_GHOST}`}
        >
          取消
        </button>
      </div>
    </article>
  );
}
