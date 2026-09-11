import { useState, useRef, useCallback } from "react";
import { Card, Button, Form } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import { invalidateSkillCache, skillApi } from "../../../api/modules/skill";
import type {
  AgentProfileConfig,
  AgentSummary,
  CopyAgentRequest,
} from "../../../api/types/agents";
import { useAgentStore } from "../../../stores/agentStore";
import { useAgents } from "./useAgents";
import { AgentTable, AgentModal, CopyAgentModal } from "./components";
import { MAIL_DOMAIN_WHITELIST } from "./components/mailDomains";
import { PageHeader } from "@/components/PageHeader";
import { reorderAgents } from "./reorder";
import styles from "./index.module.less";

type ModelSettingsDraft = Pick<
  AgentProfileConfig,
  "fallback_models" | "fallback_policy" | "subagent_model"
>;

const EMPTY_MODEL_SETTINGS: ModelSettingsDraft = {
  fallback_models: [],
  fallback_policy: { enabled: true, target_scope: "configured" },
  subagent_model: null,
};

export default function AgentsPage() {
  const { t, i18n } = useTranslation();
  const {
    agents,
    loading,
    deleteAgent,
    toggleAgent,
    pinAgent,
    loadAgents,
    setAgents,
  } = useAgents();
  const { selectedAgent, setSelectedAgent } = useAgentStore();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [copyModalVisible, setCopyModalVisible] = useState(false);
  const [copyingAgent, setCopyingAgent] = useState<AgentSummary | null>(null);
  const [copying, setCopying] = useState(false);
  const [reordering, setReordering] = useState(false);
  const [form] = Form.useForm();
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [modelSettings, setModelSettings] =
    useState<ModelSettingsDraft>(EMPTY_MODEL_SETTINGS);
  const [modelSettingsResetToken, setModelSettingsResetToken] = useState(0);
  const installedSkillsRef = useRef<string[]>([]);
  const { message } = useAppMessage();

  const handleCreate = () => {
    setEditingAgent(null);
    setModelSettings(EMPTY_MODEL_SETTINGS);
    setModelSettingsResetToken((token) => token + 1);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
      active_model_provider: undefined,
      active_model_model: undefined,
      mail_mode: "none",
      mail_credential: undefined,
      mail_push: undefined,
      backend: "qwenpaw",
    });
    setSelectedSkills([]);
    installedSkillsRef.current = [];
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    try {
      setSelectedSkills([]);
      installedSkillsRef.current = [];
      invalidateSkillCache({ agentId: agent.id });
      const config = await agentsApi.getAgent(agent.id);
      setEditingAgent(agent);
      const { mail, ...configRest } = config;
      form.setFieldsValue({
        ...configRest,
        active_model_provider: config.active_model?.provider_id || undefined,
        active_model_model: config.active_model?.model || undefined,
        mail_mode: mail
          ? mail.is_new_account
            ? "dedicated"
            : "personal"
          : "none",
        mail_credential: mail ? mail.credential : undefined,
        mail_push: mail?.push
          ? {
              mode: mail.push.mode ?? "off",
              // Legacy field "subject" is displayed and saved as
              // "content" (subject + body matching).
              rules: (mail.push.rules ?? []).map((rule) =>
                rule.field === "subject"
                  ? { ...rule, field: "content" as const }
                  : rule,
              ),
              poll_interval_seconds: mail.push.poll_interval_seconds,
              // Missing in legacy configs → backend defaults to false.
              access_control_enabled: mail.push.access_control_enabled ?? false,
            }
          : undefined,
      });
      setModalVisible(true);
    } catch (error) {
      console.error("Failed to load agent config:", error);
      message.error(t("agent.loadConfigFailed"));
    }
  };

  const handleDelete = async (agentId: string) => {
    try {
      await deleteAgent(agentId);

      if (selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      message.error(t("agent.deleteFailed"));
    }
  };

  const handleOpenCopy = (agent: AgentSummary) => {
    setCopyingAgent(agent);
    setCopyModalVisible(true);
  };

  const handleCopy = async (body: CopyAgentRequest) => {
    if (!copyingAgent) {
      return;
    }

    setCopying(true);
    try {
      const result = await agentsApi.copyAgent(copyingAgent.id, body);
      message.success(`${t("agent.copySuccess")} (ID: ${result.id})`);
      setCopyModalVisible(false);
      setCopyingAgent(null);
      await loadAgents();
    } catch (error: unknown) {
      console.error("Failed to copy agent:", error);
      message.error(
        error instanceof Error ? error.message : t("agent.copyFailed"),
      );
    } finally {
      setCopying(false);
    }
  };

  const handleToggle = async (agentId: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    try {
      await toggleAgent(agentId, newEnabled);

      if (!newEnabled && selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      // Error already handled in hook
    }
  };

  const handlePin = async (agentId: string, currentPinned: boolean) => {
    try {
      await pinAgent(agentId, !currentPinned);
    } catch {
      // Error already handled in hook
    }
  };

  const handleInstalledSkillsLoaded = useCallback((skills: string[]) => {
    installedSkillsRef.current = skills;
  }, []);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const workspaceRaw = values.workspace_dir;
      const workspace_dir =
        typeof workspaceRaw === "string"
          ? workspaceRaw.trim() || undefined
          : workspaceRaw;

      const providerId = values.active_model_provider;
      const modelId = values.active_model_model;
      const active_model =
        values.backend === "qwenpaw" && providerId && modelId
          ? { provider_id: providerId, model: modelId }
          : null;

      const {
        // Destructured only to keep them out of `rest` (already read
        // above via `values.*`); underscore + disable per project style.
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        active_model_provider: _active_model_provider,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        active_model_model: _active_model_model,
        mail_mode,
        mail_credential,
        mail_push,
        ...rest
      } = values;
      // 0.2.0: the rules editor UI is hidden, so `mail_push.rules` is no
      // longer a registered form field and won't appear in validateFields()
      // results. Read the form store directly to pass legacy rules through
      // unchanged (hidden-but-preserved policy).
      const storedMailPush = form.getFieldValue("mail_push") as
        | {
            mode?: string;
            rules?: Array<{
              field?: string;
              contains?: string;
              action?: string;
              param?: string;
            }>;
            poll_interval_seconds?: number;
            access_control_enabled?: boolean;
          }
        | undefined;
      const pushMode = mail_push?.mode ?? storedMailPush?.mode ?? "off";
      // Preserve existing rules as-is regardless of mode so editing an old
      // agent never wipes its rule config on the backend.
      const pushRules = (
        (mail_push?.rules ?? storedMailPush?.rules ?? []) as Array<{
          field?: string;
          contains?: string;
          action?: string;
          param?: string;
        }>
      ).map((rule) => ({
        // Never submit the legacy "subject" value.
        field: rule?.field === "subject" ? "content" : rule?.field || "from",
        contains: (rule?.contains ?? "").trim(),
        action: rule?.action || "notify",
        param: (rule?.param ?? "").trim(),
      }));
      const pollIntervalSeconds =
        mail_push?.poll_interval_seconds ??
        storedMailPush?.poll_interval_seconds;
      // Explicitly persist the access-control switch; access control is
      // opt-in, so a missing field falls back to disabled.
      const accessControlEnabled =
        mail_push?.access_control_enabled ??
        storedMailPush?.access_control_enabled ??
        false;
      const push =
        pushMode === "off" && pushRules.length === 0
          ? null
          : {
              mode: pushMode,
              rules: pushRules,
              ...(pollIntervalSeconds != null
                ? { poll_interval_seconds: pollIntervalSeconds }
                : {}),
              access_control_enabled: accessControlEnabled,
            };
      // Mail is only supported for the qwenpaw backend; never submit
      // mail config for third-party backends (the server rejects it).
      const mail =
        values.backend === "qwenpaw" &&
        (mail_mode === "personal" || mail_mode === "dedicated")
          ? {
              is_new_account: mail_mode === "dedicated",
              credential: {
                name: (mail_credential?.name ?? "").trim(),
                domain: mail_credential?.domain || "163.com",
                // Whitelisted domains must use an empty provider; custom
                // enterprise domains carry the selected provider.
                provider: MAIL_DOMAIN_WHITELIST.includes(
                  mail_credential?.domain || "163.com",
                )
                  ? ""
                  : mail_credential?.provider || "",
                auth_code: mail_credential?.auth_code || "",
              },
              ...(push ? { push } : {}),
            }
          : null;
      const payload = { ...rest, workspace_dir, active_model, mail };

      if (editingAgent) {
        const previousInstalledSkills = installedSkillsRef.current;
        const newSkills =
          values.backend === "qwenpaw"
            ? selectedSkills.filter(
                (skill) => !previousInstalledSkills.includes(skill),
              )
            : [];

        for (const skill of newSkills) {
          await skillApi.downloadSkillPoolSkill({
            skill_name: skill,
            targets: [{ workspace_id: editingAgent.id }],
          });
        }
        await agentsApi.updateAgent(editingAgent.id, payload);
        installedSkillsRef.current = [
          ...previousInstalledSkills,
          ...newSkills.filter(
            (skill) => !previousInstalledSkills.includes(skill),
          ),
        ];
        invalidateSkillCache({ agentId: editingAgent.id });
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent({
          ...payload,
          ...(values.backend === "qwenpaw" ? modelSettings : {}),
          language: i18n.language,
          skill_names: values.backend === "qwenpaw" ? selectedSkills : [],
        });
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      setModalVisible(false);
      await loadAgents();
    } catch (error: unknown) {
      console.error("Failed to save agent:", error);
      if (editingAgent) {
        invalidateSkillCache({ agentId: editingAgent.id });
      }
      message.error(
        error instanceof Error ? error.message : t("agent.saveFailed"),
      );
    }
  };

  const handleReorder = async (activeId: string, overId: string) => {
    const nextAgents = reorderAgents(agents, activeId, overId);
    if (nextAgents === agents) {
      return;
    }

    const previousAgents = agents;
    setAgents(nextAgents);
    setReordering(true);

    try {
      await agentsApi.reorderAgents(nextAgents.map((agent) => agent.id));
      message.success(t("agent.reorderSuccess"));
    } catch (error) {
      console.error("Failed to reorder agents:", error);
      setAgents(previousAgents);
      message.error(t("agent.reorderFailed"));
    } finally {
      setReordering(false);
    }
  };

  return (
    <div className={styles.agentsPage}>
      <PageHeader
        parent={t("agent.parent")}
        current={t("agent.agents")}
        extra={
          <div className={styles.headerRight}>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreate}
            >
              {t("agent.create")}
            </Button>
          </div>
        }
      />

      <Card className={styles.tableCard}>
        <AgentTable
          agents={agents}
          loading={loading || reordering}
          reordering={reordering}
          onEdit={handleEdit}
          onCopy={handleOpenCopy}
          onDelete={handleDelete}
          onToggle={handleToggle}
          onPin={handlePin}
          onReorder={handleReorder}
        />
      </Card>

      <AgentModal
        open={modalVisible}
        editingAgent={editingAgent}
        form={form}
        selectedSkills={selectedSkills}
        onSelectedSkillsChange={setSelectedSkills}
        onInstalledSkillsLoaded={handleInstalledSkillsLoaded}
        modelSettings={editingAgent ? undefined : modelSettings}
        modelSettingsResetToken={modelSettingsResetToken}
        onModelSettingsChange={(settings) => setModelSettings(settings)}
        onSave={handleSubmit}
        onCancel={() => setModalVisible(false)}
      />

      <CopyAgentModal
        open={copyModalVisible}
        sourceAgent={copyingAgent}
        confirmLoading={copying}
        onOk={handleCopy}
        onCancel={() => {
          setCopyModalVisible(false);
          setCopyingAgent(null);
        }}
      />
    </div>
  );
}
