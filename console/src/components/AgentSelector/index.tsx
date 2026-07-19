import { Select, Tooltip } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import {
  Bot,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  Pin,
  Power,
  PowerOff,
} from "lucide-react";
import { SparkDownLine, SparkUpLine } from "@agentscope-ai/icons";
import { useAgentStore } from "../../stores/agentStore";
import { agentsApi } from "../../api/modules/agents";
import type { AgentSummary } from "../../api/types/agents";
import { useTranslation } from "react-i18next";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import { useNavigate } from "react-router-dom";
import { useAppMessage } from "../../hooks/useAppMessage";
import { AgentStatusIndicator } from "../AgentStatusIndicator";
import { useAgentLongPress } from "./useAgentLongPress";
import styles from "./index.module.less";

interface AgentSelectorProps {
  collapsed?: boolean;
}

export default function AgentSelector({
  collapsed = false,
}: AgentSelectorProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { selectedAgent, agents, setSelectedAgent, setAgents, refreshAgents } =
    useAgentStore();
  const { message } = useAppMessage();
  const messageRef = useRef(message);
  const translationRef = useRef(t);
  messageRef.current = message;
  translationRef.current = t;
  const [loading, setLoading] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [disabledExpanded, setDisabledExpanded] = useState(false);
  const [togglingAgentId, setTogglingAgentId] = useState<string | null>(null);
  const [pinningAgentId, setPinningAgentId] = useState<string | null>(null);

  const loadAgents = useCallback(
    async (showLoading = true, reportError = true) => {
      try {
        if (showLoading) {
          setLoading(true);
        }
        await refreshAgents();
      } catch (error) {
        console.error("Failed to load agents:", error);
        if (reportError) {
          messageRef.current.error(translationRef.current("agent.loadFailed"));
        }
      } finally {
        if (showLoading) {
          setLoading(false);
        }
      }
    },
    [refreshAgents],
  );

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  const enabledAgents = useMemo(
    () => agents.filter((agent) => agent.enabled),
    [agents],
  );
  const pinnedAgents = useMemo(
    () => agents.filter((agent) => agent.id === "default" || agent.pinned),
    [agents],
  );
  const regularEnabledAgents = useMemo(
    () =>
      agents.filter(
        (agent) => agent.enabled && agent.id !== "default" && !agent.pinned,
      ),
    [agents],
  );
  const regularDisabledAgents = useMemo(
    () =>
      agents.filter(
        (agent) => !agent.enabled && agent.id !== "default" && !agent.pinned,
      ),
    [agents],
  );

  const handleChange = (value: string) => {
    const targetAgent = agents.find((agent) => agent.id === value);
    if (!targetAgent?.enabled) return;
    setSelectedAgent(value);
    message.success(t("agent.switchSuccess"));
  };

  useEffect(() => {
    if (!agents.length || selectedAgent === "default") return;

    const currentAgent = agents.find((agent) => agent.id === selectedAgent);
    if (!currentAgent) {
      setSelectedAgent("default");
      message.warning(t("agent.currentAgentDeleted"));
    } else if (!currentAgent.enabled) {
      setSelectedAgent("default");
      message.warning(t("agent.currentAgentDisabled"));
    }
  }, [agents, message, selectedAgent, setSelectedAgent, t]);

  const stopSelectorAction = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const handleToggleAgent = async (
    agent: AgentSummary,
    nextEnabled: boolean,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    stopSelectorAction(event);
    if (togglingAgentId !== null) return;

    setTogglingAgentId(agent.id);
    if (nextEnabled) {
      setAgents(
        agents.map((item) =>
          item.id === agent.id
            ? {
                ...item,
                enabled: true,
                startup_status: "starting",
              }
            : item,
        ),
      );
    }

    try {
      await agentsApi.toggleAgentEnabled(agent.id, nextEnabled);
      if (!nextEnabled && selectedAgent === agent.id) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
      message.success(
        nextEnabled ? t("agent.enableSuccess") : t("agent.disableSuccess"),
      );
    } catch (error: unknown) {
      message.error(
        error instanceof Error ? error.message : t("agent.toggleFailed"),
      );
    } finally {
      await loadAgents(false, false);
      setTogglingAgentId(null);
    }
  };

  const handlePinAgent = useCallback(
    async (agent: AgentSummary) => {
      if (agent.id === "default" || pinningAgentId !== null) return;
      const nextPinned = !agent.pinned;
      setPinningAgentId(agent.id);
      setAgents(
        agents.map((item) =>
          item.id === agent.id ? { ...item, pinned: nextPinned } : item,
        ),
      );

      try {
        await agentsApi.setAgentPinned(agent.id, nextPinned);
        message.success(
          nextPinned ? t("agent.pinSuccess") : t("agent.unpinSuccess"),
        );
      } catch (error: unknown) {
        message.error(
          error instanceof Error ? error.message : t("agent.pinFailed"),
        );
      } finally {
        await loadAgents(false, false);
        setPinningAgentId(null);
      }
    },
    [agents, loadAgents, message, pinningAgentId, setAgents, t],
  );
  const { getLongPressProps, pressingId, feedbackId } = useAgentLongPress(
    (agent) => {
      void handlePinAgent(agent);
    },
  );

  const currentAgentInfo = agents.find((agent) => agent.id === selectedAgent);

  if (collapsed) {
    return (
      <Tooltip
        title={
          currentAgentInfo
            ? getAgentDisplayName(currentAgentInfo, t)
            : selectedAgent
        }
        placement="right"
        overlayInnerStyle={{ background: "rgba(0,0,0,0.75)", color: "#fff" }}
      >
        <div className={styles.agentSelectorCollapsed}>
          <Bot size={18} strokeWidth={2} />
          {currentAgentInfo && (
            <span className={styles.collapsedStatusIndicator}>
              <AgentStatusIndicator
                status={currentAgentInfo.startup_status}
                enabled={currentAgentInfo.enabled}
              />
            </span>
          )}
        </div>
      </Tooltip>
    );
  }

  const renderToggleButton = (agent: AgentSummary, nextEnabled: boolean) => {
    const isToggling = togglingAgentId === agent.id;
    const startupInProgress =
      agent.startup_status === "pending" || agent.startup_status === "starting";
    const disabled =
      togglingAgentId !== null || (!nextEnabled && startupInProgress);
    const label = nextEnabled
      ? t("agent.enableAgent", { name: getAgentDisplayName(agent, t) })
      : t("agent.disableAgent", { name: getAgentDisplayName(agent, t) });

    return (
      <Tooltip
        title={
          !nextEnabled && startupInProgress
            ? t("agent.status.waitUntilStarted")
            : label
        }
      >
        <button
          type="button"
          className={styles.agentToggleButton}
          disabled={disabled}
          aria-label={label}
          onMouseDown={stopSelectorAction}
          onClick={(event) => {
            void handleToggleAgent(agent, nextEnabled, event);
          }}
        >
          {isToggling ? (
            <LoaderCircle
              size={15}
              className={styles.toggleSpinner}
              aria-hidden="true"
            />
          ) : nextEnabled ? (
            <Power size={15} aria-hidden="true" />
          ) : (
            <PowerOff size={15} aria-hidden="true" />
          )}
        </button>
      </Tooltip>
    );
  };

  const renderAgentDetails = (agent: AgentSummary, disabled: boolean) => (
    <div
      className={[
        styles.agentOption,
        disabled ? styles.agentOptionDisabled : "",
        pressingId === agent.id ? styles.agentOptionPressing : "",
        feedbackId === agent.id ? styles.agentOptionPinFeedback : "",
      ]
        .filter(Boolean)
        .join(" ")}
      title={
        agent.id === "default"
          ? t("agent.defaultPinned")
          : agent.pinned
          ? t("agent.longPressToUnpin")
          : t("agent.longPressToPin")
      }
      {...getLongPressProps(agent)}
    >
      <div className={styles.agentOptionHeader}>
        <div className={styles.agentStatusColumn}>
          <AgentStatusIndicator
            status={agent.startup_status}
            enabled={agent.enabled}
          />
        </div>
        <div className={styles.agentOptionIcon}>
          <Bot size={16} strokeWidth={2} />
        </div>
        <div className={styles.agentOptionContent}>
          <div className={styles.agentOptionName}>
            <span className={styles.agentOptionNameText}>
              {getAgentDisplayName(agent, t)}
            </span>
            {(agent.id === "default" || agent.pinned) && (
              <Pin
                size={12}
                strokeWidth={2.2}
                className={styles.pinnedIndicator}
                aria-label={t("agent.pinned")}
              />
            )}
            {agent.id === selectedAgent && (
              <CheckCircle
                size={14}
                strokeWidth={2}
                className={styles.activeIndicator}
              />
            )}
          </div>
          {agent.description && (
            <div className={styles.agentOptionDescription}>
              {agent.description}
            </div>
          )}
        </div>
        {agent.id !== "default" && renderToggleButton(agent, !agent.enabled)}
      </div>
      <div className={styles.agentOptionId}>{`ID: ${agent.id}`}</div>
    </div>
  );

  return (
    <div className={styles.agentSelectorWrapper}>
      <div className={styles.agentSelectorLabel}>
        <span>
          {t("agent.currentWorkspace")}
          {enabledAgents.length > 0 && (
            <span className={styles.agentCountBadge}>
              {` (${enabledAgents.length})`}
            </span>
          )}
        </span>
      </div>
      <Select
        value={selectedAgent}
        onChange={handleChange}
        loading={loading}
        className={styles.agentSelector}
        placeholder={t("agent.selectAgent")}
        optionLabelProp="label"
        popupClassName={styles.agentSelectorDropdown}
        onOpenChange={setDropdownOpen}
        suffixIcon={
          dropdownOpen ? <SparkUpLine size={20} /> : <SparkDownLine size={20} />
        }
        popupRender={(menu) => (
          <div className={styles.dropdownContent}>
            <div className={styles.dropdownHeader}>
              <span className={styles.dropdownHeaderTitle}>
                {t("agent.currentWorkspace")}
              </span>
              <button
                type="button"
                className={styles.managementLink}
                onMouseDown={stopSelectorAction}
                onClick={(event) => {
                  stopSelectorAction(event);
                  navigate("/agents");
                }}
              >
                {t("agent.management")}
                <ChevronRight size={12} strokeWidth={2.5} />
              </button>
            </div>
            <div className={styles.enabledAgentList}>{menu}</div>
            {regularDisabledAgents.length > 0 && (
              <div className={styles.disabledAgentSection}>
                <button
                  type="button"
                  className={styles.disabledAgentHeader}
                  aria-expanded={disabledExpanded}
                  aria-controls="disabled-agent-list"
                  onMouseDown={stopSelectorAction}
                  onClick={(event) => {
                    stopSelectorAction(event);
                    setDisabledExpanded((expanded) => !expanded);
                  }}
                >
                  <span>
                    {t("agent.disabledAgents", {
                      count: regularDisabledAgents.length,
                    })}
                  </span>
                  <ChevronDown
                    size={15}
                    className={
                      disabledExpanded ? styles.disabledChevronExpanded : ""
                    }
                  />
                </button>
                {disabledExpanded && (
                  <div
                    id="disabled-agent-list"
                    className={styles.disabledAgentList}
                  >
                    {regularDisabledAgents.map((agent) => (
                      <div key={agent.id} className={styles.disabledAgentRow}>
                        {renderAgentDetails(agent, true)}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      >
        <Select.OptGroup label={t("agent.pinnedAgents")}>
          {pinnedAgents.map((agent) => (
            <Select.Option
              key={agent.id}
              value={agent.id}
              disabled={!agent.enabled}
              label={
                <div className={styles.selectedAgentLabel}>
                  <AgentStatusIndicator
                    status={agent.startup_status}
                    enabled={agent.enabled}
                  />
                  <Bot size={14} strokeWidth={2} />
                  <span>{getAgentDisplayName(agent, t)}</span>
                </div>
              }
            >
              {renderAgentDetails(agent, !agent.enabled)}
            </Select.Option>
          ))}
        </Select.OptGroup>
        {regularEnabledAgents.length > 0 && (
          <Select.OptGroup label={t("agent.otherAgents")}>
            {regularEnabledAgents.map((agent) => (
              <Select.Option
                key={agent.id}
                value={agent.id}
                label={
                  <div className={styles.selectedAgentLabel}>
                    <AgentStatusIndicator
                      status={agent.startup_status}
                      enabled={agent.enabled}
                    />
                    <Bot size={14} strokeWidth={2} />
                    <span>{getAgentDisplayName(agent, t)}</span>
                  </div>
                }
              >
                {renderAgentDetails(agent, false)}
              </Select.Option>
            ))}
          </Select.OptGroup>
        )}
      </Select>
    </div>
  );
}
