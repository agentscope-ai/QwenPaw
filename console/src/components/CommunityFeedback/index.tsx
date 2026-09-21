import { lazy, Suspense, useState } from "react";
import { Dropdown } from "antd";
import { ChevronDown, MessageSquareText, LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { InstallationOrigin } from "@/api/types/community";
import { communityConnectionApi } from "@/api/modules/community";
import { useAppMessage } from "@/hooks/useAppMessage";
import { PostComposer } from "@/pages/CommunityFeedback/PostComposer";
import styles from "./index.module.less";

const ResourceReportModal = lazy(() =>
  import("@/pages/CommunityFeedback/ResourceReportModal").then((module) => ({
    default: module.ResourceReportModal,
  })),
);

export function hasCommunityFeedback(
  origin: InstallationOrigin | null | undefined,
): origin is InstallationOrigin {
  return (
    origin?.provider === "agentscope-platform" &&
    typeof origin.resource_id === "string" &&
    origin.resource_id.trim().length > 0 &&
    ["plugin", "app", "skill"].includes(origin.resource_type)
  );
}

interface CommunityFeedbackProps {
  origin?: InstallationOrigin | null;
  resourceName: string;
  /** Cards reserve their own top row; lists keep the action beside the name. */
  variant?: "corner" | "inline";
}

export function CommunityFeedback({
  origin,
  resourceName,
  variant = "corner",
}: CommunityFeedbackProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(false);
  const [composeOpen, setComposeOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  if (!hasCommunityFeedback(origin)) return null;

  const handleOpen = () => setComposeOpen(true);
  const handleAssist = async () => {
    setLoading(true);
    try {
      const status = await communityConnectionApi.status();
      if (status.status === "connected") setReportOpen(true);
      else setComposeOpen(true);
    } catch {
      message.error(t("communityCompose.loginRequired"));
    } finally {
      setLoading(false);
    }
  };

  const button = (
    <button
      type="button"
      className={styles.button}
      disabled={loading}
      aria-busy={loading}
      aria-label={t("communityFeedback.forResource", {
        defaultValue: "Report an issue with {{name}}",
        name: resourceName,
      })}
      onClick={(event) => {
        event.stopPropagation();
        void handleOpen();
      }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {loading ? (
        <LoaderCircle size={12} className={styles.spinner} aria-hidden="true" />
      ) : (
        <MessageSquareText size={12} aria-hidden="true" />
      )}
      {t("communityFeedback.reportIssue", "Report an issue")}
    </button>
  );
  return (
    <span
      className={variant === "corner" ? styles.corner : styles.inline}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {button}
      <Dropdown
        trigger={["click"]}
        menu={{
          items: [{ key: "assist", label: t("communityReport.useAgent") }],
          onClick: () => void handleAssist(),
        }}
      >
        <button
          type="button"
          className={styles.button}
          aria-label={t("communityReport.moreOptions")}
          disabled={loading}
        >
          <ChevronDown size={12} aria-hidden="true" />
        </button>
      </Dropdown>
      {composeOpen && (
        <PostComposer
          onClose={() => setComposeOpen(false)}
          origin={origin}
          resourceName={resourceName}
        />
      )}
      {reportOpen && (
        <Suspense fallback={null}>
          <ResourceReportModal
            open={reportOpen}
            onClose={() => setReportOpen(false)}
            origin={origin}
            resourceName={resourceName}
          />
        </Suspense>
      )}
    </span>
  );
}
