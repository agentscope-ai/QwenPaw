import { captureSkillScope, useSkillScope } from "@/api/skillScope";
import { createSkillGovernanceApi } from "@/api/modules/skillGovernance";
import { useState, useRef, useCallback, useEffect } from "react";
import { Card, Button, Form, Tabs } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "../../../api/modules/agents";
import { modelCatalogApi } from "../../../api/modules/modelCatalog";
import {
  createSkillApi,
  invalidateSkillCache,
} from "../../../api/modules/skill";
import type {
  AdminAgentSummary,
  AgentSummary,
  CopyAgentRequest,
} from "../../../api/types/agents";
import type { ModelSlotConfig } from "../../../api/types/provider";
import {
  pickAccessibleAgentId,
  useAgentStore,
} from "../../../stores/agentStore";
import { useAgents } from "./useAgents";
import {
  AdminAgentsTable,
  AgentMembersModal,
  AgentTable,
  AgentModal,
  toAgentActiveModel,
  CopyAgentModal,
} from "./components";
import { useAuthStore } from "../../../stores/authStore";
import { PageHeader } from "@/components/PageHeader";
import { reorderAgents } from "./reorder";
import { groupAgentsByAccess } from "./groupAgents";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t, i18n } = useTranslation();
  const skillScope = useSkillScope();
  const navigate = useNavigate();
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
  const [membersAgentId, setMembersAgentId] = useState<string | null>(null);
  const [adminAgents, setAdminAgents] = useState<AdminAgentSummary[]>([]);
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminEditingAgentId, setAdminEditingAgentId] = useState<string | null>(
    null,
  );
  const [form] = Form.useForm();
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [globalActiveModel, setGlobalActiveModel] =
    useState<ModelSlotConfig | null>(null);
  const installedSkillsRef = useRef<string[]>([]);
  const importInputRef = useRef<HTMLInputElement>(null);
  const editSequence = useRef(0);
  const { message } = useAppMessage();
  const groupedAgents = groupAgentsByAccess(agents);
  const isAdmin = useAuthStore(
    (state) => state.user?.platform_role === "admin",
  );

  const loadAdminAgents = useCallback(async () => {
    if (!isAdmin) return;
    setAdminLoading(true);
    try {
      setAdminAgents((await agentsApi.listAdminAgents()).agents);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("common.error"));
    } finally {
      setAdminLoading(false);
    }
  }, [isAdmin, message, t]);

  useEffect(() => {
    void loadAdminAgents();
  }, [loadAdminAgents]);

  useEffect(() => {
    void modelCatalogApi
      .default()
      .then((result) => setGlobalActiveModel(result.active_llm ?? null))
      .catch(() => setGlobalActiveModel(null));
  }, []);

  useEffect(() => {
    setModalVisible(false);
    setEditingAgent(null);
    setSelectedSkills([]);
    installedSkillsRef.current = [];
  }, [skillScope.key]);

  const handleCreate = () => {
    editSequence.current++;
    setEditingAgent(null);
    setAdminEditingAgentId(null);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
      active_model_provider: undefined,
      active_model_model: undefined,
      backend: "qwenpaw",
    });
    setSelectedSkills([]);
    installedSkillsRef.current = [];
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    const scope = captureSkillScope(agent.id);
    const sequence = ++editSequence.current;
    try {
      setSelectedSkills([]);
      installedSkillsRef.current = [];
      invalidateSkillCache({ agentId: agent.id });
      const config = await agentsApi.getAgent(agent.id);
      scope.assert();
      if (sequence !== editSequence.current) return;
      setEditingAgent(agent);
      setAdminEditingAgentId(null);
      form.setFieldsValue({
        ...config,
        active_model_provider: config.active_model?.provider_id || undefined,
        active_model_model: config.active_model?.model || undefined,
      });
      setModalVisible(true);
    } catch (error) {
      if (!scope.current()) return;
      console.error("Failed to load agent config:", error);
      message.error(t("agent.loadConfigFailed"));
    }
  };

  const handleAdminEdit = async (agent: AdminAgentSummary) => {
    const scope = captureSkillScope(agent.id);
    const sequence = ++editSequence.current;
    try {
      const config = await agentsApi.getAdminAgent(agent.id);
      scope.assert();
      if (sequence !== editSequence.current) return;
      setAdminEditingAgentId(agent.id);
      setEditingAgent({
        id: agent.id,
        name: agent.name,
        description: agent.description,
        workspace_dir: config.workspace_dir ?? "",
        enabled: agent.status === "active",
        backend: config.backend ?? "qwenpaw",
        access_role: "owner",
      });
      form.setFieldsValue({
        ...config,
        active_model_provider: config.active_model?.provider_id || undefined,
        active_model_model: config.active_model?.model || undefined,
      });
      setModalVisible(true);
    } catch (error) {
      if (!scope.current()) return;
      message.error(error instanceof Error ? error.message : t("common.error"));
    }
  };

  const handleAdminRuntimeConfig = (agent: AdminAgentSummary) => {
    const params = new URLSearchParams({
      governance: "runtime-config",
      agentId: agent.id,
      agentName: agent.name,
      ownerUserId: agent.owner_user_id,
    });
    navigate(`/agent-config?${params.toString()}`);
  };

  const handleAdminMemoryFiles = (agent: AdminAgentSummary) => {
    const params = new URLSearchParams({
      governance: "runtime-config",
      agentId: agent.id,
      agentName: agent.name,
    });
    navigate(`/files?${params.toString()}`);
  };

  const handleDelete = async (agentId: string) => {
    try {
      await deleteAgent(agentId);

      if (selectedAgent === agentId) {
        const fallbackAgentId = pickAccessibleAgentId(
          agents.filter((agent) => agent.id !== agentId),
          "",
        );
        setSelectedAgent(fallbackAgentId);
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

  const handleExport = async (agent: AgentSummary) => {
    try {
      await agentsApi.exportPortableAgent(agent.id, agent.name);
      message.success(t("agent.exportPortableSuccess"));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("agent.exportPortableFailed"),
      );
    }
  };

  const handleImport = async (file: File) => {
    try {
      const result = await agentsApi.importPortableAgent(file);
      await loadAgents();
      message.success(t("agent.importPortableSuccess", { name: result.name }));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("agent.importPortableFailed"),
      );
    } finally {
      if (importInputRef.current) importInputRef.current.value = "";
    }
  };

  const handleToggle = async (agentId: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    try {
      await toggleAgent(agentId, newEnabled);

      if (!newEnabled && selectedAgent === agentId) {
        setSelectedAgent(
          pickAccessibleAgentId(
            agents.filter((agent) => agent.id !== agentId),
            "",
          ),
        );
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
    const scope = captureSkillScope(editingAgent?.id);
    if (!scope.ready) return;
    const sequence = editSequence.current;
    const assertCurrentEdit = () => {
      scope.assert();
      if (sequence !== editSequence.current)
        throw new DOMException("Agent editor changed", "AbortError");
    };
    try {
      const values = await form.validateFields();
      assertCurrentEdit();
      const workspaceRaw = values.workspace_dir;
      const workspace_dir =
        typeof workspaceRaw === "string"
          ? workspaceRaw.trim() || undefined
          : workspaceRaw;

      const active_model = toAgentActiveModel(values);

      const payload = { ...values, workspace_dir, active_model };
      delete payload.active_model_provider;
      delete payload.active_model_model;

      if (adminEditingAgentId) {
        await agentsApi.updateAdminAgent(adminEditingAgentId, payload);
        assertCurrentEdit();
        message.success(t("agent.updateSuccess"));
      } else if (editingAgent) {
        const previousInstalledSkills = installedSkillsRef.current;
        const newSkills =
          values.backend === "qwenpaw"
            ? selectedSkills.filter(
                (skill) => !previousInstalledSkills.includes(skill),
              )
            : [];

        if (newSkills.length) {
          if (!scope.canEdit) throw new Error(t("skillGovernance.forbidden"));
          if (scope.multiUser) {
            const governance = createSkillGovernanceApi(scope);
            const catalog = (await governance.catalog()).items;
            for (const name of newSkills) {
              assertCurrentEdit();
              const skill = catalog.find((item) => item.name === name);
              if (!skill) throw new Error(t("skillGovernance.forbidden"));
              await governance.load(skill.id);
            }
          } else {
            const skills = createSkillApi(scope);
            for (const name of newSkills) {
              assertCurrentEdit();
              await skills.downloadSkillPoolSkill({
                skill_name: name,
                targets: [{ workspace_id: editingAgent.id }],
              });
            }
          }
        }
        assertCurrentEdit();
        await agentsApi.updateAgent(editingAgent.id, payload);
        assertCurrentEdit();
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
          language: i18n.language,
          skill_names:
            !scope.multiUser && values.backend === "qwenpaw"
              ? selectedSkills
              : [],
        });
        assertCurrentEdit();
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      setModalVisible(false);
      // Refreshing access changes the skill scope; both lists must refresh
      // without revalidating the completed edit against that old scope.
      await Promise.all([loadAgents(), loadAdminAgents()]);
    } catch (error: unknown) {
      if (!scope.current() || sequence !== editSequence.current) return;
      console.error("Failed to save agent:", error);
      if (editingAgent) {
        invalidateSkillCache({ agentId: editingAgent.id });
      }
      message.error(
        error instanceof Error ? error.message : t("agent.saveFailed"),
      );
    }
  };

  const handlePublication = async (
    agent: AdminAgentSummary | AgentSummary,
    published: boolean,
  ) => {
    try {
      await agentsApi.setPublication(agent.id, published);
      await Promise.all([loadAdminAgents(), loadAgents()]);
      message.success(
        t(published ? "agent.published" : "agent.publicationRevoked"),
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("common.error"));
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
      await agentsApi.reorderAgents(
        nextAgents
          .filter((agent) => agent.can_reorder !== false)
          .map((agent) => agent.id),
      );
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
            <input
              ref={importInputRef}
              type="file"
              accept=".zip,application/zip"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleImport(file);
              }}
            />
            <Button
              icon={<UploadOutlined />}
              onClick={() => importInputRef.current?.click()}
            >
              {t("agent.importPortable")}
            </Button>
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
        <Tabs
          className={styles.accessTabs}
          items={[
            ...(["owner", "collaborator", "user"] as const).map((role) => ({
              key: role,
              label: `${t(`agent.accessGroup.${role}`)} (${
                groupedAgents[role].length
              })`,
              children: (
                <AgentTable
                  agents={groupedAgents[role]}
                  loading={loading || reordering}
                  reordering={reordering}
                  onEdit={handleEdit}
                  onCopy={handleOpenCopy}
                  onExport={handleExport}
                  onDelete={handleDelete}
                  onToggle={handleToggle}
                  onPin={handlePin}
                  onReorder={handleReorder}
                  onManageMembers={(agent) => setMembersAgentId(agent.id)}
                  isAdmin={isAdmin}
                  onPublication={handlePublication}
                  globalActiveModel={globalActiveModel}
                />
              ),
            })),
            ...(isAdmin
              ? [
                  {
                    key: "admin-all",
                    label: `${t("agent.accessGroup.adminAll")} (${
                      adminAgents.length
                    })`,
                    children: (
                      <AdminAgentsTable
                        agents={adminAgents}
                        loading={adminLoading}
                        onEdit={handleAdminEdit}
                        onMemoryFiles={handleAdminMemoryFiles}
                        onRuntimeConfig={handleAdminRuntimeConfig}
                        onPublication={handlePublication}
                      />
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Card>

      <AgentModal
        open={modalVisible}
        editingAgent={editingAgent}
        form={form}
        selectedSkills={selectedSkills}
        onSelectedSkillsChange={setSelectedSkills}
        onInstalledSkillsLoaded={handleInstalledSkillsLoaded}
        onSave={handleSubmit}
        onCancel={() => {
          editSequence.current++;
          setModalVisible(false);
          setAdminEditingAgentId(null);
        }}
        governanceMode={adminEditingAgentId !== null}
      />

      <AgentMembersModal
        open={membersAgentId !== null}
        agentId={membersAgentId}
        onClose={() => setMembersAgentId(null)}
        onChanged={loadAgents}
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
