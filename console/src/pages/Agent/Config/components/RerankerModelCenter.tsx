import { useEffect, useRef } from "react";
import InlineHelp from "@/components/InlineHelp";
import { Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { BadgeCheck, ChevronRight, Cpu, Power, Target } from "lucide-react";

import type { RerankerHistoryRecord } from "@/api/modules/agent";
import type { RerankerConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useMemoryMaintenance } from "../memoryMaintenanceContext";
import { isRerankerConfigured } from "./rerankerUtils";
import styles from "../index.module.less";
import { useRerankerVerification } from "./useRerankerVerification";

function formRerankerConfig(form: {
  getFieldValue: (name: (string | number)[]) => unknown;
}): RerankerConfig | undefined {
  return form.getFieldValue(["reme_light_memory_config", "reranker_config"]) as
    | RerankerConfig
    | undefined;
}

export function RerankerModelCenter() {
  const { t } = useTranslation();
  const { modal } = useAppMessage();
  const form = Form.useFormInstance();
  const { configLoadRevision } = useMemoryMaintenance();

  const rerankerConfig = Form.useWatch(
    ["reme_light_memory_config", "reranker_config"],
    form,
  ) as RerankerConfig | undefined;
  const modelName = rerankerConfig?.model_name ?? "";
  const baseUrl = rerankerConfig?.base_url ?? "";
  const multiplier = rerankerConfig?.candidate_multiplier ?? 3;
  const rerankerConfigured = isRerankerConfigured(rerankerConfig);
  const {
    agentId,
    testingReranker,
    testedReranker,
    testedRerankerIsCurrent,
    history,
    configKey,
    isMounted,
    loadHistory,
    runManualProbe,
  } = useRerankerVerification(rerankerConfig, rerankerConfigured);

  // History is a separate slice and never sets verifiedAt, so a verdict can
  // only come from a completed probe of the current service.
  const verifiedReranker =
    testedReranker && testedReranker.verifiedAt > 0 ? testedReranker : null;

  // Load the persistent verification history once per agent / config load once
  // the form's reranker settings are populated. The backend resolves the saved
  // agent config and computes the fingerprint itself, and the hook scopes the
  // returned series to that service so editing to another model never shows
  // the previous model's trend.
  const loadedHistoryTokenRef = useRef<string | null>(null);
  useEffect(() => {
    if (!configKey) return;
    const token = `${agentId}:${configLoadRevision}`;
    if (loadedHistoryTokenRef.current === token) return;
    loadedHistoryTokenRef.current = token;
    void loadHistory(configKey);
  }, [agentId, configKey, configLoadRevision, loadHistory]);

  const testReranker = async () => {
    try {
      await form.validateFields([
        ["reme_light_memory_config", "reranker_config", "base_url"],
        ["reme_light_memory_config", "reranker_config", "model_name"],
      ]);
    } catch {
      return;
    }
    if (!isMounted()) return;

    const config = formRerankerConfig(form);
    if (!config || !isRerankerConfigured(config)) {
      modal.error({
        title: t("agentConfig.rerankerTestFailed"),
        content: t("agentConfig.rerankerTestIncomplete"),
      });
      return;
    }

    const outcome = await runManualProbe(config, () =>
      formRerankerConfig(form),
    );
    if (outcome.status === "stale") return;

    if (outcome.status === "success") {
      const { result } = outcome;
      const precisionLine =
        result.precision !== null
          ? t("agentConfig.rerankerPrecisionResult", {
              correct: result.correct_count,
              total: result.total,
              percent: Math.round(result.precision * 100),
            })
          : t("agentConfig.rerankerRankingUnknown");
      const detail = `${t("agentConfig.rerankerTestSuccessDetail", {
        latency: result.latency_ms,
      })} ${precisionLine}`;
      modal.success({
        title: t("agentConfig.rerankerTestSuccess"),
        content: result.history_error
          ? `${detail} (${result.history_error})`
          : detail,
      });
    } else {
      modal.error({
        title: t("agentConfig.rerankerTestFailed"),
        content: outcome.message,
      });
    }
  };

  return (
    <section className={styles.memoryOverview}>
      <div className={styles.memoryOverviewHeader}>
        <div className={styles.embeddingTitle}>
          <h3>{t("agentConfig.rerankerOverviewTitle")}</h3>
          <InlineHelp>{t("agentConfig.rerankerStatusDescription")}</InlineHelp>
        </div>
      </div>

      <div className={styles.memoryOverviewGrid}>
        <div className={styles.memoryOverviewItem}>
          <span className={styles.memoryOverviewLabel}>
            <Power size={14} aria-hidden="true" />
            {t("agentConfig.rerankerConfigStatus")}
          </span>
          <strong
            className={
              rerankerConfigured
                ? styles.embeddingStatusValueEnabled
                : styles.embeddingStatusValueDisabled
            }
          >
            <i />
            {t(
              rerankerConfigured
                ? "agentConfig.rerankerCapabilityEnabled"
                : "agentConfig.rerankerCapabilityDisabled",
            )}
          </strong>
          <small>
            {t(
              rerankerConfigured
                ? "agentConfig.rerankerStatusHintEnabled"
                : "agentConfig.rerankerStatusHintDisabled",
              rerankerConfigured ? { multiplier } : undefined,
            )}
          </small>
        </div>
        <div className={styles.memoryOverviewItem}>
          <span className={styles.memoryOverviewLabel}>
            <Cpu size={14} aria-hidden="true" />
            {t("agentConfig.rerankerCurrentModel")}
          </span>
          <strong title={modelName}>{modelName || "—"}</strong>
          <small title={baseUrl}>{baseUrl || "—"}</small>
        </div>
        <button
          type="button"
          className={`${styles.memoryOverviewItem} ${styles.memoryOverviewClickableItem} ${styles.embeddingVerificationAction}`}
          onClick={testReranker}
          disabled={!rerankerConfigured || testingReranker}
          aria-busy={testingReranker}
          aria-label={t("agentConfig.rerankerTestConnection")}
        >
          <span className={styles.memoryOverviewLabel}>
            <BadgeCheck size={14} aria-hidden="true" />
            {t("agentConfig.rerankerVerificationStatus")}
          </span>
          {testedRerankerIsCurrent && verifiedReranker ? (
            <>
              <strong className={styles.embeddingStatusValueVerified}>
                {t("agentConfig.rerankerVerified")}
              </strong>
              <small>
                {t("agentConfig.rerankerVerificationMetrics", {
                  latency: verifiedReranker.latency,
                })}
              </small>
            </>
          ) : (
            <>
              <strong className={styles.embeddingStatusValuePending}>
                {t("agentConfig.rerankerNotVerified")}
              </strong>
              <small>{t("agentConfig.rerankerVerificationHint")}</small>
            </>
          )}
          <ChevronRight size={16} aria-hidden="true" />
        </button>
        <div className={styles.memoryOverviewItem}>
          <span className={styles.memoryOverviewLabel}>
            <Target size={14} aria-hidden="true" />
            {t("agentConfig.rerankerPrecisionLabel")}
          </span>
          {verifiedReranker && testedRerankerIsCurrent ? (
            <>
              {verifiedReranker.precision !== null ? (
                <>
                  <strong className={styles.embeddingStatusValueVerified}>
                    {verifiedReranker.correctCount}/{verifiedReranker.total} ={" "}
                    {Math.round(verifiedReranker.precision * 100)}%
                  </strong>
                  {history.some((entry) => entry.precision !== null) && (
                    <small>
                      {t("agentConfig.rerankerPrecisionRolling", {
                        avg: Math.round(rollingPrecision(history) * 100),
                      })}
                    </small>
                  )}
                </>
              ) : (
                <>
                  <strong>—</strong>
                  <small>
                    {t(
                      history.length > 0
                        ? "agentConfig.rerankerPrecisionHistoryOnly"
                        : "agentConfig.rerankerPrecisionHint",
                    )}
                  </small>
                </>
              )}
              <PrecisionSparkline history={history} />
            </>
          ) : history.length > 0 ? (
            <>
              <strong>—</strong>
              <small>{t("agentConfig.rerankerPrecisionHistoryOnly")}</small>
              <PrecisionSparkline history={history} />
            </>
          ) : (
            <>
              <strong>—</strong>
              <small>{t("agentConfig.rerankerPrecisionHint")}</small>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function rollingPrecision(history: RerankerHistoryRecord[]): number {
  const values = history
    .map((entry) => entry.precision)
    .filter((value): value is number => value !== null);
  if (values.length === 0) return 0;
  const recent = values.slice(-10);
  return recent.reduce((sum, value) => sum + value, 0) / recent.length;
}

function PrecisionSparkline({ history }: { history: RerankerHistoryRecord[] }) {
  const values = history
    .map((entry) => entry.precision)
    .filter((value): value is number => value !== null);
  if (values.length < 2) return null;
  const width = 120;
  const height = 26;
  const points = values
    .map((value, index) => {
      const clamped = Math.max(0, Math.min(1, value));
      const x = (index / (values.length - 1)) * (width - 4) + 2;
      const y = height - 3 - clamped * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={styles.precisionSparkline}
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
