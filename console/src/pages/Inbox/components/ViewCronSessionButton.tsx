import { useState } from "react";
import { Button, message } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { chatApi } from "../../../api/modules/chat";
import { consoleApi } from "../../../api/modules/console";
import { useAgentStore } from "../../../stores/agentStore";
import { DEFAULT_AGENT_ID } from "../../../utils/agentDisplayName";
import type { PushMessage } from "../types";

export function ViewCronSessionButton({
  item,
  onNavigate,
}: {
  item: PushMessage;
  onNavigate: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const setSelectedAgent = useAgentStore((state) => state.setSelectedAgent);
  const runId = item.metadata?.payload?.run_id;

  if (item.metadata?.sourceType !== "cron") return null;

  const openSession = async () => {
    if (typeof runId !== "string" || !runId) return;
    setLoading(true);
    try {
      const trace = await consoleApi.getInboxTrace(runId);
      const sessionId = trace.meta?.run_session_id;
      if (typeof sessionId !== "string" || !sessionId) {
        message.info(t("inbox.sessionNotFound"));
        return;
      }
      const agentId = item.metadata?.agentId || DEFAULT_AGENT_ID;
      const chats = await chatApi.listChats({ agentId });
      // The route uses ChatSpec.id, not the runtime session_id. Match the
      // actual execution session, including jobs that share a session.
      const chat = chats.find(
        (candidate) =>
          candidate.session_id === sessionId &&
          (!trace.meta.dispatch_channel ||
            candidate.channel === trace.meta.dispatch_channel) &&
          (!trace.meta.target_user_id ||
            candidate.user_id === trace.meta.target_user_id),
      );
      if (!chat) {
        message.info(t("inbox.sessionNotFound"));
        return;
      }
      setSelectedAgent(agentId);
      onNavigate();
      navigate(`/chat/${encodeURIComponent(chat.id)}`);
    } catch {
      message.error(t("inbox.openSessionFailed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      type="link"
      style={{ fontSize: 15 }}
      loading={loading}
      disabled={typeof runId !== "string" || !runId}
      onClick={() => void openSession()}
    >
      {t("inbox.viewSession")}
    </Button>
  );
}
