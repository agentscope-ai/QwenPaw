import { useEffect, useRef } from "react";
import InlineHelp from "@/components/InlineHelp";
import { Form } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { BadgeCheck, ChevronRight, Cpu, Power, Target } from "lucide-react";

import { api } from "@/api";
import type { RerankerHistoryRecord } from "@/api/modules/agent";
import type { RerankerConfig } from "@/api/types/agent";
import { useAppMessage } from "@/hooks/useAppMessage";
import { isRerankerConfigured } from "./rerankerUtils";
import styles from "../index.module.less";
import { useRerankerVerification } from "./useRerankerVerification";

function formRerankerConfig(form: {
  getFieldValue: (name: (string | number)[]) => unknown;
}): RerankerConfig | undefined {
  return form.getFieldValue([
    "reme_light_memory_config",
    "reranker_config",
  ]) as RerankerConfig | undefined;
}

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
    agentId,
    testingReranker,
    setTestingReranker,
    testedReranker,
    testedRerankerIsCurrent,
    history,
    configKey,
    markVerified,
    setHistory,
    clearVerification,
  } = useRerankerVerification(rerankerConfig, rerankerConfigured);

  // History is a separate slice and never sets verifiedAt, so a verdict can
  // only come from a completed probe of the current service.
  const verifiedReranker =
    testedReranker && testedReranker.verifiedAt > 0 ? testedReranker : null;

  // Request identity for the manual probe: a late response must not touch
  // state, dialogs or the loading flag once the agent or config changed.
  const requestIdRef = useRef(0);
  const agentIdRef = useRef(agentId);
  const configKeyRef = useRef(configKey);
  useEffect(() => {
    agentIdRef.current = agentId;
  }, [agentId]);
  useEffect(() => {
    configKeyRef.current = configKey;
  }, [configKey]);

  // Load the persistent verification history from the backend. The backend
  // resolves the saved agent config and computes the fingerprint itself, so
  // the console never needs `crypto.subtle` (unavailable on plain HTTP).
  useEffect(() => {
    let cancelled = false;
    api
      .getRerankerHistory()
      .then((res) => {
        if (!cancelled) setHistory(res.history);
      })
      .catch(() => {
        // History is best-effort; a failed fetch must not block the UI.
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, setHistory]);

  const testReranker = async () => {
    try {
      await form.validateFields([
        ["reme_light_memory_config", "reranker_config", "base_url"],
        ["reme_light_memory_config", "reranker_config", "model_name"],
      ]);
    } catch {
      return;
    }

    const config = formRerankerConfig(form);
    if (!config || !isRerankerConfigured(config)) {
      modal.error({
        title: t("agentConfig.rerankerTestFailed"),
        content: t("agentConfig.rerankerTestIncomplete"),
      });
      return;
    }

    setTestingReranker(true);
    const requestId = ++requestIdRef.current;
    const testedAgentId = agentId;
    const testedConfigKey = configKey;
    // The response is only applicable while this exact test is the latest
    // request, for the same agent, with the same still-configured settings.
    const isCurrent = () =>
      requestId === requestIdRef.current &&
      agentIdRef.current === testedAgentId &&
      configKeyRef.current === testedConfigKey &&
      isRerankerConfigured(formRerankerConfig(form));

    try {
      const result = await api.testReranker(config);
      if (!isCurrent()) return;
      if (result.success) {
        await markVerified(
          result.latency_ms,
          result.precision,
          result.correct_count,
          result.total,
          testedConfigKey,
        );
        // The backend appends this run to history before responding; refresh
        // the trend from the same series (no second file read).
        setHistory(result.history ?? []);
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
      if (!isCurrent()) return;
      clearVerification();
      modal.error({
        title: t("agentConfig.rerankerTestFailed"),
        content: error instanceof Error ? error.message : String(error),
      });
    } finally {
      // A newer request owns the loading flag; an older one must not clear it.
      if (requestId === requestIdRef.current) setTestingReranker(false);
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
                  <small>
                    {t("agentConfig.rerankerPrecisionRolling", {
                      avg: Math.round(rollingPrecision(history) * 100),
                    })}
                  </small>
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
              <small>
                {t("agentConfig.rerankerPrecisionHistoryOnly")}
              </small>
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
