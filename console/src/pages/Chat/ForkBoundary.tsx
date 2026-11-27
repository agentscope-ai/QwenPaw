import { Tooltip } from "antd";
import { GitFork } from "lucide-react";
import styles from "./ForkBoundary.module.less";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useChatAnywhereOptions } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereOptionsContext";
import {
  findSessionByReference,
  useSessionListStore,
} from "../../stores/sessionListStore";
import { extractTranscriptTurnId, type CopyableResponse } from "./utils";

export function ForkBoundary({ data }: { data: CopyableResponse }) {
  const { t } = useTranslation();
  const chatId = useChatAnywhereOptions(
    (options) => options.session?.currentSessionId,
  );
  const session = useSessionListStore((state) =>
    chatId
      ? findSessionByReference(
          state.sessions,
          chatId,
          state.resolvedRouteSession,
        )
      : undefined,
  );
  const parent = useSessionListStore((state) =>
    session?.parentChatId
      ? findSessionByReference(state.sessions, session.parentChatId)
      : undefined,
  );
  if (
    !session?.parentChatId ||
    !session.forkTurnId ||
    session.forkTurnId !== extractTranscriptTurnId(data)
  )
    return null;

  const label = t("chat.forkBoundary", {
    name: parent
      ? parent.name || t("chat.forkParent")
      : t("chat.forkParentUnavailable"),
  });
  const content = (
    <>
      <GitFork size={16} aria-hidden="true" />
      <span>{label}</span>
    </>
  );
  return (
    <div className={styles.boundary} role="separator">
      <Tooltip title={label} trigger={["hover", "focus"]}>
        {parent ? (
          <Link
            className={styles.link}
            to={`/chat/${encodeURIComponent(session.parentChatId)}`}
          >
            {content}
          </Link>
        ) : (
          <span className={styles.link} aria-disabled="true" tabIndex={0}>
            {content}
          </span>
        )}
      </Tooltip>
    </div>
  );
}
