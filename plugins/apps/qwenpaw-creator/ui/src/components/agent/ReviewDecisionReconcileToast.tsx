import { useEffect } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

/**
 * Correction toast for the "error but actually committed" decision path:
 * when a decide() call fails but the store's follow-up poll discovers the
 * decided operations were recorded as accepted, show a correction so users
 * do not retry or distrust the result. When the review only leaves the
 * pending list without a recorded decision value (another tab may have
 * rejected it), the outcome stays unconfirmed instead of being reported as
 * success. Mounted next to DecisionTray because the review card itself
 * unmounts on resolution.
 */
export default function ReviewDecisionReconcileToast({
  projectId,
}: {
  projectId: string;
}) {
  const { t } = useTranslation();
  const reconciled = useFileProjectReviewStore((state) =>
    state.projectId === projectId ? state.reconciledDecision : null,
  );
  const unconfirmed = useFileProjectReviewStore((state) =>
    state.projectId === projectId ? state.unconfirmedDecision : null,
  );
  const clearReconciledDecision = useFileProjectReviewStore(
    (state) => state.clearReconciledDecision,
  );
  const clearUnconfirmedDecision = useFileProjectReviewStore(
    (state) => state.clearUnconfirmedDecision,
  );

  useEffect(() => {
    if (!reconciled) return;
    message.success(t("fileReview.public.decisionReconciled"));
    clearReconciledDecision();
  }, [reconciled, clearReconciledDecision, t]);

  useEffect(() => {
    if (!unconfirmed) return;
    message.warning(t("fileReview.public.decisionUnconfirmed"));
    clearUnconfirmedDecision();
  }, [unconfirmed, clearUnconfirmedDecision, t]);

  return null;
}
