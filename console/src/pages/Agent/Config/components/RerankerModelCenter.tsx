import InlineHelp from "@/components/InlineHelp";
import { Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { BadgeCheck, ChevronRight, Cpu, Power, Target } from "lucide-react";

import { api } from "@/api";
import type { RerankerConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { isRerankerConfigured } from "./rerankerUtils";
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
    clearVerification,
  } = useRerankerVerification(rerankerConfig, rerankerConfigured);

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
        markVerified(result.latency_ms, result.ranking_correct, result.scores);
        const scoresText =
          result.scores?.map((score) => score.toFixed(3)).join(" / ") ?? "";
        const rankingLine =
          result.ranking_correct === true
            ? t("agentConfig.rerankerRankingCorrect", { scores: scoresText })
            : result.ranking_correct === false
            ? t("agentConfig.rerankerRankingIncorrect", {
                scores: scoresText,
              })
            : t("agentConfig.rerankerRankingUnknown");
        modal.success({
          title: t("agentConfig.rerankerTestSuccess"),
          content: `${t("agentConfig.rerankerTestSuccessDetail", {
            latency: result.latency_ms,
          })} ${rankingLine}`,
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
          {testedRerankerIsCurrent &&
          testedReranker &&
          testedReranker.rankingCorrect !== null ? (
            <>
              <strong
                className={
                  testedReranker.rankingCorrect
                    ? styles.embeddingStatusValueVerified
                    : styles.embeddingStatusValuePending
                }
              >
                {testedReranker.rankingCorrect ? 100 : 0}%
              </strong>
              <small
                title={testedReranker.scores
                  ?.map((score) => score.toFixed(3))
                  .join(" / ")}
              >
                {testedReranker.scores
                  ?.map((score) => score.toFixed(3))
                  .join(" / ")}
              </small>
            </>
          ) : (
            <>
              <strong>—</strong>
              <small>
                {t(
                  testedRerankerIsCurrent && testedReranker
                    ? "agentConfig.rerankerPrecisionNoScores"
                    : "agentConfig.rerankerPrecisionHint",
                )}
              </small>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
