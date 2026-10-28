import { useEffect } from "react";
import InlineHelp from "@/components/InlineHelp";
import { Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { BadgeCheck, ChevronRight, Cpu, Power, Target } from "lucide-react";

import { api } from "@/api";
import type { RerankerHistoryRecord } from "@/api/modules/agent";
import type { RerankerConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  getRerankerServiceFingerprint,
  isRerankerConfigured,
} from "./rerankerUtils";
import styles from "../index.module.less";
import { useRerankerVerification } from "./useRerankerVerification";

export function RerankerModelCenter() {
  const { t } = useTranslation();
  const { modal } = useAppMessage();
  const form = Form.useFormInstance();

  const rerankerConfig = Form.useWatch(
    ["reme_light_memory_config", "reranker_config"],
    form,
  ) as RerankerConfig | undefined;
  const modelName = rerankerConfig?.model_name ?? "";
  const baseUrl = rerankerConfig?.base_url ?? "";
  const multiplier = rerankerConfig?.candidate_multiplier ?? 3;
  const rerankerConfigured = isRerankerConfigured(rerankerConfig);
  const {
    testingReranker,
    setTestingReranker,
    testedReranker,
    testedRerankerIsCurrent,
    markVerified,
    setHistory,
    clearVerification,
  } = useRerankerVerification(rerankerConfig, rerankerConfigured);

  const serviceFingerprint = rerankerConfigured
    ? getRerankerServiceFingerprint(rerankerConfig)
    : "";

  // Load the persistent verification history for the current service so the
  // precision slot can show a trend even before a manual verification.
  useEffect(() => {
    if (!serviceFingerprint) return;
    let cancelled = false;
    api
      .getRerankerHistory(serviceFingerprint)
      .then((res) => {
        if (!cancelled) setHistory(res.history);
      })
      .catch(() => {
        // History is best-effort; a failed fetch must not block the UI.
      });
    return () => {
      cancelled = true;
    };
  }, [serviceFingerprint, setHistory]);

  const testReranker = async () => {
    try {
      await form.validateFields([
        ["reme_light_memory_config", "reranker_config", "base_url"],
        ["reme_light_memory_config", "reranker_config", "model_name"],
      ]);
    } catch {
      return;
    }

    const config = form.getFieldValue([
      "reme_light_memory_config",
      "reranker_config",
    ]) as RerankerConfig | undefined;
    if (!config || !isRerankerConfigured(config)) {
      modal.error({
        title: t("agentConfig.rerankerTestFailed"),
        content: t("agentConfig.rerankerTestIncomplete"),
      });
      return;
    }

    setTestingReranker(true);
    try {
      const result = await api.testReranker(config);
      if (result.success) {
        markVerified(
          result.latency_ms,
          result.precision,
          result.correct_count,
          result.total,
          result.history ?? [],
        );
        const precisionLine =
          result.precision !== null
            ? t("agentConfig.rerankerPrecisionResult", {
                correct: result.correct_count,
                total: result.total,
                percent: Math.round(result.precision * 100),
              })
            : t("agentConfig.rerankerRankingUnknown");
        modal.success({
          title: t("agentConfig.rerankerTestSuccess"),
          content: `${t("agentConfig.rerankerTestSuccessDetail", {
            latency: result.latency_ms,
          })} ${precisionLine}`,
        });
      } else {
        clearVerification();
        modal.error({
          title: t("agentConfig.rerankerTestFailed"),
          content: result.message,
        });
      }
    } catch (error) {
      clearVerification();
      modal.error({
        title: t("agentConfig.rerankerTestFailed"),
        content: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setTestingReranker(false);
    }
  };

  return (
    <section className={styles.memoryOverview}>
      <div className={styles.memoryOverviewHeader}>
        <div className={styles.embeddingTitle}>
          <h3>{t("agentConfig.rerankerOverviewTitle")}</h3>
          <InlineHelp>
            {t("agentConfig.rerankerStatusDescription")}
          </InlineHelp>
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
          {testedRerankerIsCurrent && testedReranker ? (
            <>
              <strong className={styles.embeddingStatusValueVerified}>
                {t("agentConfig.rerankerVerified")}
              </strong>
              <small>
                {t("agentConfig.rerankerVerificationMetrics", {
                  latency: testedReranker.latency,
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
          {testedRerankerIsCurrent && testedReranker ? (
            <>
              {testedReranker.verifiedAt > 0 &&
              testedReranker.precision !== null ? (
                <>
                  <strong className={styles.embeddingStatusValueVerified}>
                    {testedReranker.correctCount}/{testedReranker.total} ={" "}
                    {Math.round(testedReranker.precision * 100)}%
                  </strong>
                  <small>
                    {t("agentConfig.rerankerPrecisionRolling", {
                      avg: Math.round(
                        rollingPrecision(testedReranker.history) * 100,
                      ),
                    })}
                  </small>
                </>
              ) : (
                <>
                  <strong>—</strong>
                  <small>
                    {t(
                      testedReranker.history.length > 0
                        ? "agentConfig.rerankerPrecisionHistoryOnly"
                        : "agentConfig.rerankerPrecisionHint",
                    )}
                  </small>
                </>
              )}
              <PrecisionSparkline history={testedReranker.history} />
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

function PrecisionSparkline({
  history,
}: {
  history: RerankerHistoryRecord[];
}) {
  const values = history
    .map((entry) => entry.precision)
    .filter((value): value is number => value !== null);
  if (values.length < 2) return null;
  const width = 120;
  const height = 26;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * (width - 4) + 2;
      const y = height - 3 - value * (height - 6);
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
