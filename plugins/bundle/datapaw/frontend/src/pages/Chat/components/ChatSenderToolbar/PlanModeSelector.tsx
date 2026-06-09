import { useCallback, useEffect, useMemo, useState, type FC, type ReactNode } from "react";
import { Popover, Radio } from "@agentscope-ai/design";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { Bot, ChevronDown, GitBranch } from "lucide-react";
import { useTranslation } from "react-i18next";
import { datapawApi, type ChatMode } from "../../../../api/modules/datapaw";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useAgentStore } from "../../../../stores/agentStore";
import { resolveBackendSessionId } from "./utils";
import styles from "./index.module.less";

const MODE_OPTIONS: Array<{
  value: ChatMode;
  labelKey: string;
  icon: ReactNode;
}> = [
  {
    value: "plan",
    labelKey: "chat.planMode.plan",
    icon: <GitBranch size={16} />,
  },
  {
    value: "agent",
    labelKey: "chat.planMode.agent",
    icon: <Bot size={16} />,
  },
];

const PlanModeSelector: FC = () => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const { currentSessionId } = useChatAnywhereSessionsState();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<ChatMode>("agent");
  const [loading, setLoading] = useState(false);

  const backendSessionId = useMemo(
    () => resolveBackendSessionId(currentSessionId),
    [currentSessionId],
  );

  useEffect(() => {
    if (!backendSessionId) {
      setMode("agent");
      return;
    }

    let cancelled = false;
    datapawApi
      .getMode(selectedAgent, backendSessionId)
      .then((res) => {
        if (!cancelled) {
          setMode(res.mode);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMode("agent");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [backendSessionId, selectedAgent]);

  const handleSelect = useCallback(
    async (nextMode: ChatMode) => {
      if (!backendSessionId || nextMode === mode) {
        setOpen(false);
        return;
      }

      setLoading(true);
      try {
        const res = await datapawApi.setMode(
          selectedAgent,
          backendSessionId,
          nextMode,
        );
        setMode(res.mode);
        setOpen(false);
      } catch (error) {
        console.error("Failed to update chat mode:", error);
        message.error(t("chat.planMode.updateFailed"));
      } finally {
        setLoading(false);
      }
    },
    [backendSessionId, message, mode, selectedAgent, t],
  );

  const content = (
    <div className={styles.panel}>
      <Radio.Group
        value={mode}
        onChange={(event) => void handleSelect(event.target.value as ChatMode)}
        className={styles.optionList}
        disabled={loading || !backendSessionId}
      >
        {MODE_OPTIONS.map((item) => (
          <label key={item.value} className={styles.optionRow} htmlFor={`mode-${item.value}`}>
            <span className={styles.optionLeft}>
              <span className={styles.triggerIcon}>{item.icon}</span>
              <span className={styles.optionLabel}>{t(item.labelKey)}</span>
            </span>
            <Radio id={`mode-${item.value}`} value={item.value} />
          </label>
        ))}
      </Radio.Group>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement="topLeft"
      open={open}
      onOpenChange={setOpen}
    >
      <button
        type="button"
        className={`${styles.trigger} ${open ? styles.triggerOpen : ""}`}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={loading}
      >
        <span className={styles.triggerIcon}>
          <GitBranch size={14} />
        </span>
        <span>{t("chat.planMode.label")}</span>
        <span className={styles.triggerChevron}>
          <ChevronDown size={14} />
        </span>
      </button>
    </Popover>
  );
};

export default PlanModeSelector;
