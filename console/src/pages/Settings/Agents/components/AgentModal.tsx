import { useMemo } from "react";
import {
  Modal,
  Form,
  Input,
  Switch,
  InputNumber,
  Select,
  Card,
  Divider,
} from "antd";
import { useTranslation } from "react-i18next";
import type { AgentSummary, ModelSlotConfig } from "@/api/types/agents";
import type { ProviderInfo } from "@/api/types/provider";

interface AgentModalProps {
  open: boolean;
  editingAgent: AgentSummary | null;
  form: ReturnType<typeof Form.useForm>[0];
  agentsList: { value: string; label: string }[];
  providers: ProviderInfo[];
  defaultModel?: ModelSlotConfig;
  onSave: () => Promise<void>;
  onCancel: () => void;
}

/**
 * Check if a provider is eligible (has models and is properly configured).
 * Same logic as ModelSelector component.
 */
function isProviderEligible(p: ProviderInfo): boolean {
  const hasModels = (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
  if (!hasModels) return false;
  if (p.is_local) return true;
  if (p.require_api_key === false) return !!p.base_url;
  if (p.is_custom) return !!p.base_url;
  if (p.require_api_key ?? true) return !!p.api_key;
  return true;
}

export function AgentModal({
  open,
  editingAgent,
  form,
  agentsList,
  providers,
  defaultModel,
  onSave,
  onCancel,
}: AgentModalProps) {
  const { t } = useTranslation();

  // Filter eligible providers (same logic as ModelSelector)
  const eligibleProviders = useMemo(
    () => providers.filter(isProviderEligible),
    [providers],
  );

  // Build provider options from eligible providers only
  const providerOptions = useMemo(
    () =>
      eligibleProviders.map((p) => ({
        value: p.id,
        label: p.name || p.id,
      })),
    [eligibleProviders],
  );

  // Get models for selected provider
  const getModelsForProvider = (providerId: string) => {
    const provider = eligibleProviders.find((p) => p.id === providerId);
    if (!provider) return [];
    const allModels = [
      ...(provider.models || []),
      ...(provider.extra_models || []),
    ];
    return allModels.map((m) => ({
      value: m.id,
      label: m.name || m.id,
    }));
  };

  // Format default model for display
  const formatDefaultModel = () => {
    if (!defaultModel?.provider_id || !defaultModel?.model) return null;
    const provider = providers.find((p) => p.id === defaultModel.provider_id);
    const allModels = provider
      ? [...(provider.models || []), ...(provider.extra_models || [])]
      : [];
    const model = allModels.find((m) => m.id === defaultModel.model);
    if (provider && model) {
      return `${provider.name || provider.id} / ${model.name || model.id}`;
    }
    return `${defaultModel.provider_id} / ${defaultModel.model}`;
  };

  const defaultModelDisplay = formatDefaultModel();

  return (
    <Modal
      title={
        editingAgent
          ? t("agent.editTitle", { name: editingAgent.name })
          : t("agent.createTitle")
      }
      open={open}
      onOk={onSave}
      onCancel={onCancel}
      width={700}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical" autoComplete="off">
        {editingAgent && (
          <Form.Item name="id" label={t("agent.id")}>
            <Input disabled />
          </Form.Item>
        )}
        <Form.Item
          name="name"
          label={t("agent.name")}
          rules={[{ required: true, message: t("agent.nameRequired") }]}
        >
          <Input placeholder={t("agent.namePlaceholder")} />
        </Form.Item>
        <Form.Item name="description" label={t("agent.description")}>
          <Input.TextArea
            placeholder={t("agent.descriptionPlaceholder")}
            rows={3}
          />
        </Form.Item>
        <Form.Item
          name="workspace_dir"
          label={t("agent.workspace")}
          help={!editingAgent ? t("agent.workspaceHelp") : undefined}
        >
          <Input
            placeholder="~/.copaw/workspaces/my-agent"
            disabled={!!editingAgent}
          />
        </Form.Item>

        {editingAgent && (
          <>
            <Divider />

            {/* Model Selection */}
            <Card
              title={t("agent.modelSettings")}
              size="small"
              style={{ marginBottom: 16 }}
            >
              <Form.Item
                name={["active_model", "provider_id"]}
                label={t("agent.provider")}
                tooltip={t("agent.providerTooltip")}
              >
                <Select
                  placeholder={t("agent.providerPlaceholder")}
                  options={providerOptions}
                  allowClear
                  showSearch
                  filterOption={(input, option) =>
                    (option?.label ?? "")
                      .toString()
                      .toLowerCase()
                      .includes(input.toLowerCase())
                  }
                  onChange={() => {
                    // Clear model when provider changes
                    form.setFieldValue(["active_model", "model"], undefined);
                  }}
                />
              </Form.Item>

              <Form.Item
                noStyle
                shouldUpdate={(prev, curr) =>
                  prev?.active_model?.provider_id !==
                  curr?.active_model?.provider_id
                }
              >
                {({ getFieldValue }) => {
                  const providerId = getFieldValue([
                    "active_model",
                    "provider_id",
                  ]);
                  const modelOptions = providerId
                    ? getModelsForProvider(providerId)
                    : [];
                  return (
                    <Form.Item
                      name={["active_model", "model"]}
                      label={t("agent.model")}
                      tooltip={t("agent.modelTooltip")}
                    >
                      <Select
                        placeholder={t("agent.modelPlaceholder")}
                        options={modelOptions}
                        allowClear
                        showSearch
                        filterOption={(input, option) =>
                          (option?.label ?? "")
                            .toString()
                            .toLowerCase()
                            .includes(input.toLowerCase())
                        }
                        disabled={!providerId}
                        notFoundContent={
                          !providerId
                            ? t("agent.selectProviderFirst")
                            : undefined
                        }
                      />
                    </Form.Item>
                  );
                }}
              </Form.Item>

              {defaultModelDisplay && (
                <Form.Item label={t("agent.defaultModel")}>
                  <span style={{ color: "#666" }}>{defaultModelDisplay}</span>
                </Form.Item>
              )}
            </Card>

            {/* Orchestration */}
            <Card
              title={t("agentConfig.orchestrationTitle")}
              size="small"
              style={{ marginBottom: 16 }}
            >
              <Form.Item
                name={["orchestration", "can_spawn_agents"]}
                label={t("agentConfig.canSpawnAgents")}
                valuePropName="checked"
                tooltip={t("agentConfig.canSpawnAgentsTooltip")}
              >
                <Switch />
              </Form.Item>

              <Form.Item
                noStyle
                shouldUpdate={(prevValues, currentValues) =>
                  prevValues?.orchestration?.can_spawn_agents !==
                  currentValues?.orchestration?.can_spawn_agents
                }
              >
                {({ getFieldValue }) =>
                  getFieldValue(["orchestration", "can_spawn_agents"]) ? (
                    <>
                      <Form.Item
                        name={["orchestration", "allowed_agents"]}
                        label={t("agentConfig.allowedAgents")}
                        tooltip={t("agentConfig.allowedAgentsTooltip")}
                      >
                        <Select
                          mode="multiple"
                          placeholder={t(
                            "agentConfig.allowedAgentsPlaceholder",
                          )}
                          options={agentsList}
                          allowClear
                          showSearch
                          filterOption={(input, option) =>
                            (option?.label ?? "")
                              .toString()
                              .toLowerCase()
                              .includes(input.toLowerCase())
                          }
                        />
                      </Form.Item>

                      <Form.Item
                        name={["orchestration", "max_spawn_depth"]}
                        label={t("agentConfig.maxSpawnDepth")}
                        tooltip={t("agentConfig.maxSpawnDepthTooltip")}
                        rules={[
                          {
                            type: "number",
                            min: 1,
                            max: 10,
                            message: t("agentConfig.maxSpawnDepthRange"),
                          },
                        ]}
                      >
                        <InputNumber
                          min={1}
                          max={10}
                          style={{ width: "100%" }}
                        />
                      </Form.Item>
                    </>
                  ) : null
                }
              </Form.Item>
            </Card>
          </>
        )}
      </Form>
    </Modal>
  );
}
