import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RefreshCw, ServerOff, ShieldAlert } from "lucide-react";
import { useCreatorBackendHealthStore } from "@/store/creatorBackendHealthStore";

/**
 * Creator 后端不可达时（宿主 SPA catch-all 把请求 partial-match 成 405，
 * 或后端尚未加载）展示的界面。只依赖 Creator 自己的 /health 探测结果，
 * 不改宿主行为。
 */

function RetryButton({ className }: { className?: string }) {
  const { t } = useTranslation();
  const probing = useCreatorBackendHealthStore((state) => state.probing);
  const check = useCreatorBackendHealthStore((state) => state.check);
  const checking = probing;
  return (
    <button
      type="button"
      className={className ?? "btn-primary"}
      disabled={checking}
      onClick={() => void check()}
      data-backend-retry=""
    >
      {checking ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <RefreshCw className="h-4 w-4" />
      )}
      {checking ? t("backendStatus.checking") : t("backendStatus.retry")}
    </button>
  );
}

function ErrorDetail({ error }: { error: string | null }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <details className="mt-4 w-full text-left">
      <summary className="cursor-pointer text-xs text-[var(--color-text-tertiary)]">
        {t("backendStatus.errorDetail")}
      </summary>
      <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-md bg-[var(--color-bg-secondary)] p-2 text-xs text-[var(--color-text-secondary)]">
        {error}
      </pre>
    </details>
  );
}

/** 首次进入页面就探测失败：整页接管，避免用户对着必然报错的表单操作。 */
export function CreatorBackendNotReadyPage() {
  const { t } = useTranslation();
  const error = useCreatorBackendHealthStore((state) => state.error);
  return (
    <div
      data-creator-backend-not-ready=""
      className="flex min-h-screen w-full items-center justify-center bg-[var(--color-bg-secondary)] p-6"
    >
      <div className="flex w-full max-w-[540px] flex-col items-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[rgba(255,127,22,0.12)] text-[var(--color-accent)]">
          <ServerOff className="h-6 w-6" />
        </div>
        <h1 className="mt-4 text-lg font-semibold text-[var(--color-text-primary)]">
          {t("backendStatus.title")}
        </h1>
        <p className="mt-2 text-sm leading-6 text-[var(--color-text-secondary)]">
          {t("backendStatus.desc")}
        </p>
        <ol className="mt-5 w-full space-y-2 text-left text-sm text-[var(--color-text-secondary)]">
          {["step1", "step2", "step3"].map((step, index) => (
            <li key={step} className="flex gap-2">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--color-bg-secondary)] text-xs font-semibold text-[var(--color-text-tertiary)]">
                {index + 1}
              </span>
              <span className="leading-6">{t(`backendStatus.${step}`)}</span>
            </li>
          ))}
        </ol>
        <div className="mt-6">
          <RetryButton />
        </div>
        <ErrorDetail error={error} />
      </div>
    </div>
  );
}

/**
 * 会话中途后端失联：默认遮挡整个应用以拦截必然失败的写操作，
 * 用户仍可显式「仅浏览」关闭本轮提示（下次探测失败会再次出现）。
 */
export function CreatorBackendBlockingOverlay() {
  const { t } = useTranslation();
  const phase = useCreatorBackendHealthStore((state) => state.phase);
  const error = useCreatorBackendHealthStore((state) => state.error);
  const checkedAt = useCreatorBackendHealthStore((state) => state.checkedAt);
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);

  if (
    phase !== "unavailable" ||
    (checkedAt !== null && dismissedAt === checkedAt)
  ) {
    return null;
  }

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={t("backendStatus.banner")}
      data-creator-backend-blocked=""
      className="fixed inset-0 z-[1050] flex items-start justify-center bg-black/40 p-6 pt-24"
    >
      <div className="flex w-full max-w-[480px] flex-col items-start gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 shadow-xl">
        <div className="flex items-center gap-2 text-[var(--color-accent)]">
          <ShieldAlert className="h-5 w-5" />
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">
            {t("backendStatus.title")}
          </h2>
        </div>
        <p className="text-sm leading-6 text-[var(--color-text-secondary)]">
          {t("backendStatus.blocked")} — {t("backendStatus.banner")}
        </p>
        <ErrorDetail error={error} />
        <div className="mt-2 flex w-full items-center justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setDismissedAt(checkedAt)}
            data-backend-browse-only=""
          >
            {t("backendStatus.browseOnly")}
          </button>
          <RetryButton />
        </div>
      </div>
    </div>
  );
}
