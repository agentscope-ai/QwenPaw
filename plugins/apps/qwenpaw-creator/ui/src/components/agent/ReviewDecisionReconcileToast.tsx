import { useEffect } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

/**
 * Correction toast for the "error but actually committed" decision path:
 * when a decide() call fails but the store's follow-up poll discovers the
 * decided operations are gone (the decision did commit server-side), show
 * a correction so users do not retry or distrust the result. Mounted next
 * to DecisionTray because the review card itself unmounts on resolution.
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
  const clearReconciledDecision = useFileProjectReviewStore(
    (state) => state.clearReconciledDecision,
  );

  useEffect(() => {
    if (!reconciled) return;
    message.success(t("fileReview.public.decisionReconciled"));
    clearReconciledDecision();
  }, [reconciled, clearReconciledDecision, t]);

  return null;
}
