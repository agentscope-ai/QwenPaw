import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChartNoAxesCombined, RotateCw, X } from "lucide-react";
import { Select } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { InteractiveCard } from "../components/interaction/InteractiveCard";
import SidebarUsageDialog from "./SidebarUsageDialog";
import { tokenUsageApi } from "../api/modules/tokenUsage";
import type { TokenUsageSummary } from "../api/types/tokenUsage";
import styles from "./sidebarA.module.less";

const BottomSheet = lazy(() => import("../components/interaction/BottomSheet"));
const Trend = lazy(() => import("./SidebarUsageTrend"));

/** Load real usage on demand; the capsule and detail share one visual surface. */
export default function SidebarUsage({
  mobile,
  agentId,
}: {
  mobile: boolean;
  agentId?: string;
}) {
  const { t } = useTranslation();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState<TokenUsageSummary>();
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [modelKey, setModelKey] = useState("");
  const [modelSummary, setModelSummary] = useState<TokenUsageSummary>();
  const [modelError, setModelError] = useState(false);
  const range = useMemo(() => {
    if (!open) return null;
    const end = new Date(),
      start = new Date();
    start.setDate(start.getDate() - 6);
    const date = (value: Date) =>
      `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(
        2,
        "0",
      )}-${String(value.getDate()).padStart(2, "0")}`;
    return { start_date: date(start), end_date: date(end) };
  }, [open]);
  useEffect(() => {
    setSummary(undefined);
    setModelKey("");
    setModelSummary(undefined);
    setError(false);
  }, [agentId]);
  useEffect(() => {
    if (!open || !range) return;
    let alive = true;
    setError(false);
    tokenUsageApi
      .getTokenUsage(range)
      .then((value) => {
        if (alive) setSummary(value);
      })
      .catch(() => {
        if (alive) setError(true);
      });
    return () => {
      alive = false;
    };
  }, [open, attempt, agentId, range]);
  const selectedModel = summary?.by_model?.[modelKey];
  useEffect(() => {
    if (!open || !range || !selectedModel) return;
    let alive = true;
    setModelSummary(undefined);
    setModelError(false);
    tokenUsageApi
      .getTokenUsage({
        ...range,
        model: selectedModel.model,
        provider: selectedModel.provider_id,
      })
      .then((value) => {
        if (alive) setModelSummary(value);
      })
      .catch(() => {
        if (alive) setModelError(true);
      });
    return () => {
      alive = false;
    };
  }, [open, selectedModel, range, attempt, agentId]);
  const activeSummary = modelKey ? modelSummary : summary;
  const label = t("sidebar.weeklyUsage");
  const points = useMemo(
    () =>
      Object.entries(activeSummary?.by_date ?? {})
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, stats]) => ({
          date,
          value: stats.prompt_tokens + stats.completion_tokens,
          model: selectedModel?.model || "Tokens",
        })),
    [activeSummary, selectedModel],
  );
  const chart = (modelKey ? modelError : error) ? (
    <button
      data-press
      className={styles.usageRetry}
      onClick={() => setAttempt(attempt + 1)}
    >
      <RotateCw size={16} />
      {t("common.retry")}
    </button>
  ) : !activeSummary ? (
    <div className={styles.usageLoading} role="status">
      {t("common.loading")}
    </div>
  ) : !points.length ? (
    <div className={styles.usageLoading}>{t("sidebar.noUsage")}</div>
  ) : (
    <Suspense
      fallback={
        <div className={styles.usageLoading}>{t("common.loading")}</div>
      }
    >
      <Trend points={points} label={label} mobile={mobile} />
    </Suspense>
  );
  const content = (
    <div className={styles.usageDetail}>
      {!!summary && (
        <Select
          className={styles.modelSelect}
          aria-label={t("sidebar.usageModel")}
          value={modelKey}
          onChange={(value) => {
            setModelSummary(undefined);
            setModelError(false);
            setModelKey(value);
          }}
          options={[
            { value: "", label: t("sidebar.allModels") },
            ...Object.entries(summary.by_model ?? {})
              .sort(
                ([, a], [, b]) =>
                  b.prompt_tokens +
                  b.completion_tokens -
                  (a.prompt_tokens + a.completion_tokens),
              )
              .map(([key, stats]) => ({
                value: key,
                label: [stats.model || key, stats.provider_id]
                  .filter(Boolean)
                  .join(" · "),
              })),
          ]}
          popupMatchSelectWidth
          listHeight={180}
          getPopupContainer={(node) => node.parentElement!}
        />
      )}
      <div className={styles.usageChart}>{chart}</div>
      <Link
        className={styles.usageDetailsLink}
        data-press
        to="/settings/token-usage"
        onClick={() => setOpen(false)}
      >
        {t("sidebar.usageDetails")}
        <ArrowUpRight size={15} />
      </Link>
    </div>
  );
  return (
    <>
      <InteractiveCard
        frameClassName={styles.usageFrame}
        tilt={3}
        className={styles.usageCapsule}
        style={{ borderRadius: 22 }}
      >
        <button
          ref={trigger}
          type="button"
          data-press
          onClick={() => setOpen(true)}
          aria-label={label}
          aria-haspopup="dialog"
        >
          <ChartNoAxesCombined size={18} />
          <span>{label}</span>
          <strong>
            {summary ? (
              new Intl.NumberFormat("en", {
                notation: "compact",
                maximumFractionDigits: 1,
              }).format(
                summary.total_prompt_tokens + summary.total_completion_tokens,
              )
            ) : (
              <span aria-hidden="true">—</span>
            )}
          </strong>
          <ArrowUpRight size={15} />
        </button>
      </InteractiveCard>
      {mobile ? (
        <Suspense fallback={null}>
          <BottomSheet
            open={open}
            onOpenChange={setOpen}
            title={label}
            tall
            initialSnap={0.5}
            onCloseFocus={() => trigger.current?.focus({ preventScroll: true })}
          >
            {content}
          </BottomSheet>
        </Suspense>
      ) : (
        <SidebarUsageDialog
          closeIcon={<X size={18} />}
          className={styles.usageModal}
          origin={trigger}
          open={open}
          onCancel={() => setOpen(false)}
          title={label}
          footer={null}
          width={540}
          centered
          focusTriggerAfterClose={false}
          afterClose={() => trigger.current?.focus({ preventScroll: true })}
        >
          {content}
        </SidebarUsageDialog>
      )}
    </>
  );
}
