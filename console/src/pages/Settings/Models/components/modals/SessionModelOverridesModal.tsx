import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Modal, Select, Switch } from "@agentscope-ai/design";
import { SaveOutlined, UndoOutlined } from "@ant-design/icons";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../../../api";
import type {
  AgentSessionModelsInfo,
  ModelSlotConfig,
  ProviderInfo,
  SessionModelInfo,
  SessionModelOverridesInfo,
} from "../../../../../api/types";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import { ProviderIcon } from "../ProviderIconComponent";
import styles from "../../index.module.less";

interface SessionModelOverridesModalProps {
  open: boolean;
  providers: ProviderInfo[];
  onClose: () => void;
}

interface DraftSlot {
  providerId?: string;
  model?: string;
  dirty?: boolean;
}

const sessionKey = (agentId: string, sessionId: string) =>
  `${agentId}\u0000${sessionId}`;

function formatSlot(slot?: ModelSlotConfig | null): string {
  if (!slot?.provider_id || !slot?.model) return "—";
  return `${slot.provider_id} / ${slot.model}`;
}

export function SessionModelOverridesModal({
  open,
  providers,
  onClose,
}: SessionModelOverridesModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [data, setData] = useState<SessionModelOverridesInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [featureSaving, setFeatureSaving] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftSlot>>({});

  const providerById = useMemo(
    () => new Map(providers.map((provider) => [provider.id, provider])),
    [providers],
  );

  const eligibleProviders = useMemo(
    () =>
      providers.filter((provider) => {
        const hasModels =
          provider.models.length + provider.extra_models.length > 0;
        if (!hasModels) return false;
        if (provider.require_api_key === false) return !!provider.base_url;
        if (provider.is_custom) return !!provider.base_url;
        if (provider.require_api_key ?? true) return !!provider.api_key;
        return true;
      }),
    [providers],
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getSessionModelOverrides();
      setData(next);
      setDrafts({});
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.sessionModelLoadFailed");
      message.error(errMsg);
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    if (open) {
      loadData();
    }
  }, [loadData, open]);

  const getDraft = (agentId: string, session: SessionModelInfo): DraftSlot => {
    const key = sessionKey(agentId, session.session_id);
    return (
      drafts[key] ?? {
        providerId: session.active_model?.provider_id,
        model: session.active_model?.model,
        dirty: false,
      }
    );
  };

  const getModels = (providerId?: string) => {
    const provider = providerId ? providerById.get(providerId) : undefined;
    return provider
      ? [...provider.models, ...provider.extra_models]
      : ([] as ProviderInfo["models"]);
  };

  const updateDraft = (
    agentId: string,
    sessionId: string,
    patch: DraftSlot,
  ) => {
    const key = sessionKey(agentId, sessionId);
    setDrafts((prev) => ({
      ...prev,
      [key]: {
        ...(prev[key] ?? {}),
        ...patch,
        dirty: true,
      },
    }));
  };

  const sourceLabel = (source: SessionModelInfo["model_source"]) =>
    t(`models.sessionModelSource.${source}`);

  const handleSave = async (
    agent: AgentSessionModelsInfo,
    session: SessionModelInfo,
  ) => {
    const draft = getDraft(agent.agent_id, session);
    if (!draft.providerId || !draft.model) return;

    const provider = providerById.get(draft.providerId);
    const selectedModel = getModels(draft.providerId).find(
      (model) => model.id === draft.model,
    );
    if (provider && selectedModel) {
      const confirmed = await confirmFreeModelSwitch({
        provider,
        model: selectedModel,
        t,
      });
      if (!confirmed) return;
    }

    const key = sessionKey(agent.agent_id, session.session_id);
    setSavingKey(key);
    try {
      await api.setSessionModelOverride(agent.agent_id, session.session_id, {
        provider_id: draft.providerId,
        model: draft.model,
      });
      message.success(t("models.sessionModelSaved"));
      await loadData();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.sessionModelSaveFailed");
      message.error(errMsg);
    } finally {
      setSavingKey(null);
    }
  };

  const handleReset = async (
    agent: AgentSessionModelsInfo,
    session: SessionModelInfo,
  ) => {
    const key = sessionKey(agent.agent_id, session.session_id);
    setSavingKey(key);
    try {
      await api.resetSessionModelOverride(agent.agent_id, session.session_id);
      message.success(t("models.sessionModelReset"));
      await loadData();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.sessionModelResetFailed");
      message.error(errMsg);
    } finally {
      setSavingKey(null);
    }
  };

  const handleResetAll = () => {
    Modal.confirm({
      title: t("models.sessionModelResetAllConfirmTitle"),
      content: t("models.sessionModelResetAllConfirmContent"),
      okText: t("models.sessionModelResetAll"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          const result = await api.resetAllSessionModelOverrides();
          message.success(
            t("models.sessionModelResetAllDone", {
              count: result.cleared_count,
            }),
          );
          await loadData();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.sessionModelResetFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const handleFeatureToggle = async (enabled: boolean) => {
    setFeatureSaving(true);
    try {
      await api.setSessionModelOverridesEnabled(enabled);
      message.success(
        t(
          enabled
            ? "models.sessionModelFeatureEnabled"
            : "models.sessionModelFeatureDisabled",
        ),
      );
      await loadData();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.sessionModelFeatureSaveFailed");
      message.error(errMsg);
    } finally {
      setFeatureSaving(false);
    }
  };

  const renderSession = (
    agent: AgentSessionModelsInfo,
    session: SessionModelInfo,
  ) => {
    const draft = getDraft(agent.agent_id, session);
    const models = getModels(draft.providerId);
    const canSave = !!draft.dirty && !!draft.providerId && !!draft.model;
    const key = sessionKey(agent.agent_id, session.session_id);
    const featureEnabled = data?.enabled ?? false;

    return (
      <div key={session.id} className={styles.sessionModelRow}>
        <div className={styles.sessionModelInfo}>
          <div className={styles.sessionModelNameRow}>
            <span className={styles.sessionModelName}>
              {session.name || session.session_id}
            </span>
            <span className={styles.sessionModelSource}>
              {sourceLabel(session.model_source)}
            </span>
          </div>
          <div className={styles.sessionModelMeta}>
            {session.channel} · {session.user_id} · {session.session_id}
          </div>
          <div className={styles.sessionModelCurrent}>
            {t("models.sessionModelCurrent")}:{" "}
            {session.active_model?.provider_id && (
              <ProviderIcon
                providerId={session.active_model.provider_id}
                size={14}
              />
            )}
            <span>{formatSlot(session.active_model)}</span>
          </div>
        </div>

        <div className={styles.sessionModelControls}>
          <Select
            className={styles.sessionModelProviderSelect}
            disabled={!featureEnabled}
            placeholder={t("models.selectProvider")}
            value={draft.providerId}
            onChange={(providerId) =>
              updateDraft(agent.agent_id, session.session_id, {
                providerId,
                model: undefined,
              })
            }
            options={eligibleProviders.map((provider) => ({
              value: provider.id,
              label: provider.name,
            }))}
          />
          <Select
            className={styles.sessionModelModelSelect}
            placeholder={
              models.length > 0
                ? t("models.selectModel")
                : t("models.addModelFirst")
            }
            disabled={!featureEnabled || models.length === 0}
            showSearch
            optionFilterProp="label"
            value={draft.model}
            onChange={(model) =>
              updateDraft(agent.agent_id, session.session_id, { model })
            }
            options={models.map((model) => ({
              value: model.id,
              label: `${model.name || model.id} (${model.id})`,
            }))}
          />
          <Button
            type="primary"
            icon={<SaveOutlined />}
            disabled={!featureEnabled || !canSave}
            loading={savingKey === key}
            onClick={() => handleSave(agent, session)}
          >
            {t("models.save")}
          </Button>
          <Button
            icon={<UndoOutlined />}
            disabled={!featureEnabled || session.model_source !== "session"}
            loading={savingKey === key}
            onClick={() => handleReset(agent, session)}
          >
            {t("common.reset")}
          </Button>
        </div>
      </div>
    );
  };

  return (
    <Modal
      open={open}
      title={t("models.sessionModelTitle")}
      footer={null}
      onCancel={onClose}
      destroyOnClose
      width={980}
      className={styles.sessionModelOverridesModal}
    >
      <div className={styles.sessionModelModal}>
        <div className={styles.sessionModelFeatureToggle}>
          <div>
            <div className={styles.sessionModelFeatureTitle}>
              {t("models.sessionModelFeatureLabel")}
            </div>
            <div className={styles.sessionModelFeatureDescription}>
              {t("models.sessionModelFeatureDescription")}
            </div>
          </div>
          <Switch
            checked={data?.enabled ?? false}
            loading={featureSaving}
            disabled={loading || !data}
            onChange={handleFeatureToggle}
          />
        </div>
        <div className={styles.sessionModelToolbar}>
          <p className={styles.sessionModelDescription}>
            {t("models.sessionModelDescription")}
          </p>
          <Button danger onClick={handleResetAll}>
            {t("models.sessionModelResetAll")}
          </Button>
        </div>

        {loading ? (
          <div className={styles.sessionModelLoading}>
            <Spin />
          </div>
        ) : !data?.agents.length ? (
          <div className={styles.sessionModelEmpty}>
            {t("models.sessionModelNoAgents")}
          </div>
        ) : (
          <div className={styles.sessionModelAgentList}>
            {data.agents.map((agent) => (
              <section
                key={agent.agent_id}
                className={styles.sessionModelAgent}
              >
                <div className={styles.sessionModelAgentHeader}>
                  <div>
                    <div className={styles.sessionModelAgentName}>
                      {agent.agent_name || agent.agent_id}
                    </div>
                    <div className={styles.sessionModelMeta}>
                      {agent.agent_id} · {agent.workspace_dir}
                    </div>
                  </div>
                  <div className={styles.sessionModelAgentDefault}>
                    {t("models.sessionModelDefault")}:{" "}
                    {formatSlot(agent.default_model)}
                  </div>
                </div>

                {agent.sessions.length > 0 ? (
                  <div className={styles.sessionModelRows}>
                    {agent.sessions.map((session) =>
                      renderSession(agent, session),
                    )}
                  </div>
                ) : (
                  <div className={styles.sessionModelEmpty}>
                    {agent.enabled
                      ? t("models.sessionModelNoSessions")
                      : t("models.sessionModelAgentDisabled")}
                  </div>
                )}
              </section>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
