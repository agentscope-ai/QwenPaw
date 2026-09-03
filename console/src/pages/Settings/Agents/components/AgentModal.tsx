import { useEffect, useState, useMemo } from "react";
import {
  Modal,
  Form,
  Input,
  Button,
  Select,
  Radio,
  Space,
  Switch,
  Typography,
  Empty,
  Spin,
} from "antd";
import { CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { AgentProfileConfig, AgentSummary } from "@/api/types/agents";
import type { ModelInfo } from "@/api/types/provider";
import type { ProviderInfo } from "@/api/types/provider";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { PoolSkillSpec } from "@/api/types/skill";
import { skillApi } from "@/api/modules/skill";
import { providerApi } from "@/api/modules/provider";
import { providerIcon } from "../../Models/components/providerIcon";
import { AgentModelSettings } from "../../../Chat/ModelSelector/AgentModelSettings";
import styles from "../index.module.less";
import { AgentBackendFields } from "./AgentBackendFields";
import {
  MAIL_DOMAIN_PICKER_DOMAINS,
  MAIL_DOMAIN_WHITELIST,
  MAIL_ENTERPRISE_SERVICE_DOMAINS,
} from "./mailDomains";

const { Text } = Typography;

const MAIL_DOMAIN_OPTIONS = MAIL_DOMAIN_PICKER_DOMAINS.map((domain) => ({
  value: domain,
  label: domain,
}));

// Domains whose credential is a 16-char authorization code.
const MAIL_AUTH_CODE_DOMAINS = [
  "163.com",
  "126.com",
  "yeah.net",
  "qq.com",
  "foxmail.com",
  "sina.com",
  "sina.cn",
  "gmail.com",
];

const MAIL_PROVIDER_OPTIONS: Array<{ value: string; labelKey: string }> = [
  { value: "tencent_exmail", labelKey: "agent.mailProviderTencentExmail" },
  { value: "aliyun_qiye", labelKey: "agent.mailProviderAliyunQiye" },
  { value: "netease_qiye", labelKey: "agent.mailProviderNeteaseQiye" },
];

const MAIL_DOMAIN_PATTERN =
  /^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$/;

const MAIL_PUSH_MODE_DESC_KEYS: Record<string, string> = {
  off: "agent.mailPushModeOffDesc",
  rules_only: "agent.mailPushModeRulesOnlyDesc",
  rules_then_agent: "agent.mailPushModeRulesThenAgentDesc",
  agent_all: "agent.mailPushModeAgentAllDesc",
};

// 0.2.0: rule-based modes are hidden from the UI but kept on the backend.
// A legacy value is only shown (read-only choice) while it is the current one.
const LEGACY_MAIL_PUSH_MODE_LABEL_KEYS: Record<string, string> = {
  rules_only: "agent.mailPushModeRulesOnly",
  rules_then_agent: "agent.mailPushModeRulesThenAgent",
};

interface EligibleProvider {
  id: string;
  name: string;
  models: ModelInfo[];
}

type ModelSettingsDraft = Pick<
  AgentProfileConfig,
  "fallback_models" | "fallback_policy" | "subagent_model"
>;

interface AgentModalProps {
  open: boolean;
  editingAgent: AgentSummary | null;
  form: ReturnType<typeof Form.useForm>[0];
  selectedSkills: string[];
  onSelectedSkillsChange: (skills: string[]) => void;
  onInstalledSkillsLoaded: (skills: string[]) => void;
  modelSettings?: ModelSettingsDraft;
  modelSettingsResetToken?: number;
  onModelSettingsChange?: (settings: ModelSettingsDraft) => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
}

export function AgentModal({
  open,
  editingAgent,
  form,
  selectedSkills,
  onSelectedSkillsChange,
  onInstalledSkillsLoaded,
  modelSettings,
  modelSettingsResetToken,
  onModelSettingsChange,
  onSave,
  onCancel,
}: AgentModalProps) {
  const { t } = useTranslation();
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [installedSkills, setInstalledSkills] = useState<string[]>([]);
  const [loadingSkills, setLoadingSkills] = useState(false);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);

  const selectedProviderId = Form.useWatch("active_model_provider", form);
  const selectedModelId = Form.useWatch("active_model_model", form);
  const mailMode = Form.useWatch("mail_mode", form);
  const mailPushMode = Form.useWatch(["mail_push", "mode"], form);
  const mailDomain = Form.useWatch(["mail_credential", "domain"], form);
  const mailCredential = Form.useWatch(["mail_credential", "auth_code"], form);
  const selectedBackend = Form.useWatch("backend", form) ?? "qwenpaw";

  const isCustomMailDomain =
    !!mailDomain && !MAIL_DOMAIN_WHITELIST.includes(mailDomain);

  // Whitelisted domains must submit an empty provider.
  useEffect(() => {
    if (
      !isCustomMailDomain &&
      form.getFieldValue(["mail_credential", "provider"])
    ) {
      form.setFieldValue(["mail_credential", "provider"], "");
    }
  }, [isCustomMailDomain, form]);

  const isAuthCodeDomain = MAIL_AUTH_CODE_DOMAINS.includes(mailDomain ?? "");
  const mailCredentialHintKey = useMemo(() => {
    if (
      isCustomMailDomain ||
      MAIL_ENTERPRISE_SERVICE_DOMAINS.includes(mailDomain ?? "")
    ) {
      return "agent.mailCredentialHintEnterprise";
    }
    if (mailDomain === "gmail.com") return "agent.mailCredentialHintGmail";
    if (mailDomain === "aliyun.com") return "agent.mailCredentialHintAliyun";
    return "agent.mailCredentialHintAuthCode";
  }, [mailDomain, isCustomMailDomain]);

  const eligibleProviders: EligibleProvider[] = useMemo(() => {
    return providers
      .filter((p) => {
        const hasModels =
          (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
        if (!hasModels) return false;
        if (p.require_api_key === false) return !!p.base_url;
        if (p.is_custom) return !!p.base_url;
        if (p.require_api_key ?? true) return !!p.api_key;
        return true;
      })
      .map((p) => ({
        id: p.id,
        name: p.name,
        models: [...(p.models ?? []), ...(p.extra_models ?? [])],
      }));
  }, [providers]);

  const availableModels = useMemo(() => {
    if (!selectedProviderId) return [];
    const provider = eligibleProviders.find((p) => p.id === selectedProviderId);
    return provider?.models ?? [];
  }, [selectedProviderId, eligibleProviders]);

  useEffect(() => {
    if (!open || selectedBackend !== "qwenpaw") return;

    setLoadingProviders(true);
    providerApi
      .listProviders()
      .then((data) => {
        if (Array.isArray(data)) setProviders(data);
      })
      .catch((err) => console.error("Failed to load providers:", err))
      .finally(() => setLoadingProviders(false));

    setLoadingSkills(true);

    const fetchPool = skillApi.listSkillPoolSkills();
    const fetchInstalled = editingAgent
      ? skillApi.listSkills(editingAgent.id)
      : Promise.resolve([]);

    Promise.all([fetchPool, fetchInstalled])
      .then(([pool, workspaceSkills]) => {
        const poolSkillNames = new Set(pool.map((skill) => skill.name));
        const installedSkills = workspaceSkills
          .filter((skill) => poolSkillNames.has(skill.name))
          .map((skill) => skill.name);

        setPoolSkills(pool);
        setInstalledSkills(installedSkills);
        onInstalledSkillsLoaded(installedSkills);
        if (editingAgent) {
          onSelectedSkillsChange(installedSkills);
        } else {
          onSelectedSkillsChange([]);
        }
      })
      .finally(() => setLoadingSkills(false));
  }, [
    editingAgent,
    onInstalledSkillsLoaded,
    onSelectedSkillsChange,
    open,
    selectedBackend,
  ]);

  const handleProviderChange = (providerId: string) => {
    form.setFieldsValue({
      active_model_provider: providerId,
      active_model_model: undefined,
    });
  };

  const handleClearModel = () => {
    form.setFieldsValue({
      active_model_provider: undefined,
      active_model_model: undefined,
    });
  };

  const toggleSkill = (name: string) => {
    const isInstalled = editingAgent && installedSkills.includes(name);
    if (isInstalled) return;

    if (selectedSkills.includes(name)) {
      onSelectedSkillsChange(selectedSkills.filter((s) => s !== name));
    } else {
      onSelectedSkillsChange([...selectedSkills, name]);
    }
  };

  const handleSelectAll = () => {
    const allNames = poolSkills.map((s) => s.name);
    onSelectedSkillsChange(allNames);
  };

  const handleSelectBuiltin = () => {
    const builtinNames = poolSkills
      .filter((s) => s.source === "builtin")
      .map((s) => s.name);
    onSelectedSkillsChange(
      Array.from(new Set([...installedSkills, ...builtinNames])),
    );
  };

  const handleSelectNone = () => {
    onSelectedSkillsChange(editingAgent ? [...installedSkills] : []);
  };

  return (
    <Modal
      title={
        editingAgent
          ? t("agent.editTitle", {
              name: getAgentDisplayName(editingAgent, t),
            })
          : t("agent.createTitle")
      }
      open={open}
      onOk={onSave}
      onCancel={onCancel}
      width={760}
      styles={{ body: { maxHeight: "72vh", overflowY: "auto" } }}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical" autoComplete="off">
        <Form.Item name="active_model_provider" hidden>
          <Input />
        </Form.Item>
        <Form.Item name="active_model_model" hidden>
          <Input />
        </Form.Item>

        <AgentBackendFields form={form} open={open} />

        {editingAgent && (
          <Form.Item name="id" label={t("agent.id")}>
            <Input disabled />
          </Form.Item>
        )}
        {!editingAgent && (
          <Form.Item
            name="id"
            label={t("agent.idLabel")}
            help={t("agent.idHelp")}
            rules={[
              {
                pattern: /^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$/,
                message: t("agent.idPattern"),
              },
            ]}
          >
            <Input placeholder={t("agent.idPlaceholder")} />
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
          hidden={selectedBackend !== "qwenpaw"}
          label={t("agent.model")}
          help={t("agent.modelHelp")}
        >
          <Space.Compact style={{ width: "100%" }}>
            <Select
              value={selectedProviderId || undefined}
              onChange={handleProviderChange}
              placeholder={t("agent.modelPlaceholder")}
              allowClear
              onClear={handleClearModel}
              loading={loadingProviders}
              style={{ width: "45%", gap: "8px" }}
              showSearch
              optionFilterProp="label"
              options={eligibleProviders.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
              optionRender={({ value }) => {
                const p = eligibleProviders.find((ep) => ep.id === value);
                if (!p) return value;
                return (
                  <Space size={6}>
                    <img
                      src={providerIcon(p.id)}
                      alt=""
                      style={{ width: 16, height: 16 }}
                    />
                    <span>{p.name}</span>
                  </Space>
                );
              }}
              notFoundContent={
                loadingProviders ? (
                  <Spin size="small" />
                ) : (
                  t("agent.noConfiguredModels")
                )
              }
            />
            <Select
              value={selectedModelId || undefined}
              onChange={(modelId) =>
                form.setFieldsValue({ active_model_model: modelId })
              }
              placeholder={
                selectedProviderId
                  ? t("models.model")
                  : t("agent.modelPlaceholder")
              }
              disabled={!selectedProviderId}
              style={{ width: "55%" }}
              showSearch
              optionFilterProp="label"
              options={availableModels.map((m) => ({
                value: m.id,
                label: m.name || m.id,
              }))}
            />
          </Space.Compact>
        </Form.Item>
        {selectedBackend === "qwenpaw" && (
          <Form.Item className={styles.agentRoutingFormItem}>
            <AgentModelSettings
              agentId={editingAgent?.id}
              providers={eligibleProviders}
              activeProviderId={selectedProviderId}
              activeModelId={selectedModelId}
              showThinking={false}
              initialConfig={modelSettings}
              draftResetToken={modelSettingsResetToken}
              onDraftChange={onModelSettingsChange}
            />
          </Form.Item>
        )}
        <Form.Item
          name="workspace_dir"
          label={t("agent.workspace")}
          help={!editingAgent ? t("agent.workspaceHelp") : undefined}
        >
          <Input
            placeholder="~/.qwenpaw/workspaces/my-agent"
            disabled={!!editingAgent}
          />
        </Form.Item>
        <Form.Item
          name="mail_mode"
          label={t("agent.mailManagement")}
          initialValue="none"
          hidden={selectedBackend !== "qwenpaw"}
        >
          <Radio.Group>
            <Radio value="none">{t("agent.mailModeNone")}</Radio>
            <Radio value="personal">{t("agent.mailModePersonal")}</Radio>
            <Radio value="dedicated">{t("agent.mailModeDedicated")}</Radio>
          </Radio.Group>
        </Form.Item>
        {selectedBackend === "qwenpaw" && mailMode === "personal" && (
          <>
            <Form.Item
              name={["mail_credential", "name"]}
              label={t("agent.mailName")}
              rules={[{ required: true, message: t("agent.mailNameRequired") }]}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name={["mail_credential", "domain"]}
              label={t("agent.mailDomain")}
              initialValue="163.com"
              rules={[
                { required: true, message: t("agent.mailDomainRequired") },
                {
                  pattern: MAIL_DOMAIN_PATTERN,
                  message: t("agent.mailDomainInvalid"),
                },
              ]}
            >
              <Select
                options={MAIL_DOMAIN_OPTIONS}
                placeholder={t("agent.mailDomainPlaceholder")}
              />
            </Form.Item>
            {isCustomMailDomain && (
              <Form.Item
                name={["mail_credential", "provider"]}
                label={t("agent.mailProvider")}
                rules={[
                  { required: true, message: t("agent.mailProviderRequired") },
                ]}
              >
                <Select
                  placeholder={t("agent.mailProviderPlaceholder")}
                  options={MAIL_PROVIDER_OPTIONS.map(({ value, labelKey }) => ({
                    value,
                    label: t(labelKey),
                  }))}
                />
              </Form.Item>
            )}
            <Form.Item
              name={["mail_credential", "auth_code"]}
              label={
                isAuthCodeDomain
                  ? t("agent.mailAuthCode")
                  : t("agent.mailCredentialLabel")
              }
              extra={t(mailCredentialHintKey)}
              rules={[
                {
                  required: !editingAgent,
                  message: isAuthCodeDomain
                    ? t("agent.mailAuthCodeRequired")
                    : t("agent.mailCredentialRequired"),
                },
                ...(isAuthCodeDomain
                  ? [{ len: 16, message: t("agent.mailAuthCodeLength") }]
                  : []),
              ]}
            >
              <Input.Password placeholder={t(mailCredentialHintKey)} />
            </Form.Item>
          </>
        )}
        {selectedBackend === "qwenpaw" && mailMode === "dedicated" && (
          <>
            <Form.Item
              name={["mail_credential", "name"]}
              label={t("agent.mailNameDedicated")}
              rules={[
                {
                  required: !!mailCredential,
                  message: t("agent.mailNameRequired"),
                },
              ]}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name={["mail_credential", "domain"]}
              label={t("agent.mailDomain")}
              initialValue="163.com"
              rules={[
                { required: true, message: t("agent.mailDomainRequired") },
                {
                  pattern: MAIL_DOMAIN_PATTERN,
                  message: t("agent.mailDomainInvalid"),
                },
              ]}
            >
              <Select
                options={MAIL_DOMAIN_OPTIONS}
                placeholder={t("agent.mailDomainPlaceholder")}
              />
            </Form.Item>
            {isCustomMailDomain && (
              <Form.Item
                name={["mail_credential", "provider"]}
                label={t("agent.mailProvider")}
                rules={[
                  { required: true, message: t("agent.mailProviderRequired") },
                ]}
              >
                <Select
                  placeholder={t("agent.mailProviderPlaceholder")}
                  options={MAIL_PROVIDER_OPTIONS.map(({ value, labelKey }) => ({
                    value,
                    label: t(labelKey),
                  }))}
                />
              </Form.Item>
            )}
            <Form.Item
              name={["mail_credential", "auth_code"]}
              label={
                isAuthCodeDomain
                  ? t("agent.mailAuthCodeOptional")
                  : t("agent.mailCredentialOptional")
              }
              extra={t("agent.mailDedicatedCredentialHint", {
                credentialHint: t(mailCredentialHintKey),
              })}
              rules={[
                ...(isAuthCodeDomain
                  ? [{ len: 16, message: t("agent.mailAuthCodeLength") }]
                  : []),
              ]}
            >
              <Input.Password placeholder={t(mailCredentialHintKey)} />
            </Form.Item>
          </>
        )}
        {selectedBackend === "qwenpaw" && mailMode && mailMode !== "none" && (
          <Form.Item
            name={["mail_push", "mode"]}
            label={t("agent.mailPushTitle")}
            initialValue="off"
            extra={t(MAIL_PUSH_MODE_DESC_KEYS[mailPushMode || "off"])}
          >
            <Select
              options={[
                { value: "off", label: t("agent.mailPushModeOff") },
                {
                  value: "agent_all",
                  label: t("agent.mailPushModeAgentAll"),
                },
                // Keep the legacy value selectable only while it is the
                // current one, so old configs don't show a bare value.
                // Once the user switches away it can't be selected back.
                ...(mailPushMode &&
                LEGACY_MAIL_PUSH_MODE_LABEL_KEYS[mailPushMode]
                  ? [
                      {
                        value: mailPushMode,
                        label: `${t(
                          LEGACY_MAIL_PUSH_MODE_LABEL_KEYS[mailPushMode],
                        )}${t("agent.mailPushModeLegacySuffix")}`,
                      },
                    ]
                  : []),
              ]}
            />
          </Form.Item>
        )}
        {selectedBackend === "qwenpaw" &&
          mailMode &&
          mailMode !== "none" &&
          mailPushMode &&
          mailPushMode !== "off" && (
            <Form.Item
              label={t("agent.mailAccessControl")}
              name={["mail_push", "access_control_enabled"]}
              valuePropName="checked"
              initialValue={false}
              extra={t("agent.mailAccessControlTip")}
            >
              <Switch />
            </Form.Item>
          )}
      </Form>

      <div
        style={{
          marginTop: 4,
          display: selectedBackend === "qwenpaw" ? undefined : "none",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <Text type="secondary" style={{ fontSize: 13 }}>
            {editingAgent
              ? t("agent.addSkillsToAgent")
              : t("agent.initialSkills")}
          </Text>
          <Space size={4}>
            <Button size="small" type="primary" onClick={handleSelectAll}>
              {t("agent.selectAll")}
            </Button>
            <Button size="small" type="default" onClick={handleSelectBuiltin}>
              {t("agent.selectBuiltin")}
            </Button>
            <Button size="small" type="default" onClick={handleSelectNone}>
              {t("agent.selectNone")}
            </Button>
          </Space>
        </div>

        {loadingSkills ? (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <Spin size="small" />
          </div>
        ) : poolSkills.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("agent.noPoolSkills")}
          />
        ) : (
          <div className={styles.pickerGrid}>
            {poolSkills.map((skill) => {
              const selected = selectedSkills.includes(skill.name);
              const isInstalled =
                !!editingAgent && installedSkills.includes(skill.name);
              return (
                <div
                  key={skill.name}
                  className={`${styles.pickerCard} ${
                    selected ? styles.pickerCardSelected : ""
                  } ${isInstalled ? styles.pickerCardDisabled : ""}`}
                  onClick={() => toggleSkill(skill.name)}
                >
                  {selected && (
                    <span className={styles.pickerCheck}>
                      <CheckOutlined />
                    </span>
                  )}
                  <div className={styles.pickerCardTitle}>{skill.name}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Modal>
  );
}
