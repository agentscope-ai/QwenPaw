import { useEffect, useState } from "react";
import { MessageSquareText } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { InstallationOrigin } from "@/api/types/community";
import { PostComposer } from "@/pages/CommunityFeedback/PostComposer";
import { lookupInstalledPluginLinks } from "@/api/modules/communityReport";
import styles from "./index.module.less";

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
  installedPluginId?: string;
  installedVersion?: string;
  /** Cards reserve their own top row; lists keep the action beside the name. */
  variant?: "corner" | "inline";
}

export function CommunityFeedback({
  origin,
  resourceName,
  installedPluginId,
  installedVersion,
  variant = "corner",
}: CommunityFeedbackProps) {
  const { t } = useTranslation();
  const [composeOpen, setComposeOpen] = useState(false);
  const [resolved, setResolved] = useState<{
    id: string;
    origin: InstallationOrigin;
  }>();
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setFailed(false);
    if (hasCommunityFeedback(origin) || !installedPluginId) return;
    let active = true;
    lookupInstalledPluginLinks(retry > 0)
      .then((data) => {
        if (!active) return;
        const found = data.resources.find(
          (item) => item.local_id === installedPluginId,
        );
        setResolved(
          found ? { id: installedPluginId, origin: found.origin } : undefined,
        );
        setFailed(data.lookup_failed_ids?.includes(installedPluginId) || false);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [origin, installedPluginId, retry]);
  const linkedOrigin = hasCommunityFeedback(origin)
    ? origin
    : resolved && resolved.id === installedPluginId
    ? {
        ...resolved.origin,
        installed_version:
          installedVersion || resolved.origin.installed_version,
      }
    : undefined;
  if (!hasCommunityFeedback(linkedOrigin))
    return failed ? (
      <button
        type="button"
        className={styles.button}
        title={t("communityFeedback.lookupFailed")}
        onClick={(event) => {
          event.stopPropagation();
          setRetry((value) => value + 1);
        }}
        onKeyDown={(event) => event.stopPropagation()}
      >
        {t("communityFeedback.retryLookup")}
      </button>
    ) : null;

  const button = (
    <button
      type="button"
      className={styles.button}
      aria-label={t("communityFeedback.forResource", {
        defaultValue: "Feedback and discussion for {{name}}",
        name: resourceName,
      })}
      onClick={(event) => {
        event.stopPropagation();
        setComposeOpen(true);
      }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <MessageSquareText size={14} strokeWidth={1.75} aria-hidden="true" />
      {t("communityFeedback.reportIssue", "Feedback & discussion")}
    </button>
  );
  return (
    <span
      className={variant === "corner" ? styles.corner : styles.inline}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {button}
      {composeOpen && (
        <PostComposer
          onClose={() => setComposeOpen(false)}
          origin={linkedOrigin}
          resourceName={resourceName}
        />
      )}
    </span>
  );
}
