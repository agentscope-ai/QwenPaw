import {
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Card,
  Alert,
  Switch,
} from "@agentscope-ai/design";
import { FolderOpen, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { planApi } from "../../../../api/modules/plan";
import { codingModeApi } from "../../../../api/modules/codingMode";
import { projectDirectoryApi } from "../../../../api/modules/projectDirectory";
import ProjectSelectModal from "../../../../components/ProjectSelectModal";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { MEMORY_MANAGER_BACKEND_OPTIONS } from "../../../../constants/backendMappings";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  useCodingModeStore,
} from "../../../../stores/codingModeStore";
import {
  useProjectDirectoryStore,
  useProjectDir,
} from "../../../../stores/projectDirectoryStore";
import styles from "../index.module.less";
import type { AgentRequestContext } from "../../../../api/modules/agentRequestContext";

const LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "id", label: "Bahasa Indonesia" },
  { value: "ru", label: "Русский" },
];

interface ReactAgentCardProps {
  language: string;
  savingLang: boolean;
  onLanguageChange: (value: string) => void;
  timezone: string;
  savingTimezone: boolean;
  onTimezoneChange: (value: string) => void;
  requestContext?: AgentRequestContext;
}

function ProjectDirectorySetting({
  requestContext,
}: {
  requestContext?: AgentRequestContext;
}) {
  const { t } = useTranslation();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const targetAgent = requestContext?.agentId || selectedAgent;
  const { projectDir } = useProjectDir(targetAgent);
  const setProjectDir = useProjectDirectoryStore(
    (state) => state.setProjectDir,
  );
  const [projectName, setProjectName] = useState("");
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const project = await projectDirectoryApi.get(requestContext);
      setProjectDir(
        targetAgent,
        project.is_workspace_default ? null : project.path,
      );
      setProjectName(project.name);
    } finally {
      setLoading(false);
    }
  }, [requestContext, setProjectDir, targetAgent]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <>
      <Form.Item
        label={t("agentConfig.projectDirectoryTitle")}
        tooltip={t("agentConfig.projectDirectoryDescription")}
        className={styles.reactAgentWideField}
      >
        <div className={styles.projectDirectorySetting}>
          <FolderOpen size={17} />
          <div>
            <strong>{projectName || t("codingMode.defaultWorkspace")}</strong>
            <span>
              {projectDir || t("agentConfig.projectDirectoryWorkspaceFallback")}
            </span>
          </div>
          {loading ? (
            <LoaderCircle className={styles.spin} size={16} />
          ) : (
            <Button size="small" onClick={() => setModalOpen(true)}>
              {t("agentConfig.changeProjectDirectory")}
            </Button>
          )}
        </div>
      </Form.Item>
      <ProjectSelectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onConfirm={() => {
          setModalOpen(false);
          void refresh();
        }}
        requestContext={requestContext}
      />
    </>
  );
}

function EnhancedCodeCapabilitySetting({
  requestContext,
}: {
  requestContext?: AgentRequestContext;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const targetAgent = requestContext?.agentId || selectedAgent;
  const codingMode = useCodingModeStore(
    (state) => state.codingModeByAgent[targetAgent] ?? false,
  );
  const setCodingMode = useCodingModeStore((state) => state.setCodingMode);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const mode = await codingModeApi.get(requestContext);
      setCodingMode(targetAgent, mode.enabled);
    } finally {
      setLoading(false);
    }
  }, [requestContext, targetAgent, setCodingMode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (enabled: boolean) => {
    setSaving(true);
    try {
      const result = await codingModeApi.toggle(enabled, requestContext);
      setCodingMode(targetAgent, result.enabled);
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Form.Item
      label={t("agentConfig.enhancedCodeCapability")}
      tooltip={t("agentConfig.enhancedCodeCapabilityTooltip")}
      className={styles.reactAgentWideField}
    >
      <div className={styles.switchSetting}>
        <span>{t("agentConfig.enhancedCodeCapabilityDescription")}</span>
        {loading ? (
          <LoaderCircle className={styles.spin} size={16} />
        ) : (
          <Switch
            checked={codingMode}
            loading={saving}
            onChange={(enabled) => void toggle(enabled)}
            aria-label={t("agentConfig.enhancedCodeCapability")}
          />
        )}
      </div>
    </Form.Item>
  );
}

export function ReactAgentCard({
  language,
  savingLang,
  onLanguageChange,
  timezone,
  savingTimezone,
  onTimezoneChange,
  requestContext,
}: ReactAgentCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [planConfig, setPlanConfig] = useState({
    enabled: false,
    auto_enabled: true,
    auto_execute: false,
    complexity_threshold: "medium",
  });
  const [planLoading, setPlanLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig(requestContext)
      .then((cfg) => {
        if (!cancelled) setPlanConfig(cfg);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [requestContext, selectedAgent]);

  const updatePlanConfig = useCallback(
    async (patch: Partial<typeof planConfig>) => {
      setPlanLoading(true);
      const prev = planConfig;
      const next = { ...planConfig, ...patch };
      setPlanConfig(next);
      try {
        const res = await planApi.updatePlanConfig(next, requestContext);
        setPlanConfig(res);
      } catch (err) {
        setPlanConfig(prev);
        message.error(err instanceof Error ? err.message : String(err));
      } finally {
        setPlanLoading(false);
      }
    },
    [message, planConfig, requestContext],
  );

  return (
    <Card className={styles.formCard} title={t("agentConfig.reactAgentTitle")}>
      <div className={styles.reactAgentRow}>
        <Form.Item
          label={t("agentConfig.language")}
          tooltip={t("agentConfig.languageTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            value={language}
            options={LANGUAGE_OPTIONS}
            onChange={onLanguageChange}
            loading={savingLang}
            disabled={savingLang}
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.timezone")}
          tooltip={t("agentConfig.timezoneTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            showSearch
            value={timezone}
            placeholder={t("agentConfig.selectTimezone")}
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            options={useTimezoneOptions()}
            onChange={onTimezoneChange}
            loading={savingTimezone}
            disabled={savingTimezone}
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.shellCommandTimeout")}
          name="shell_command_timeout"
          rules={[
            {
              required: true,
              message: t("agentConfig.shellCommandTimeoutRequired"),
            },
            {
              type: "number",
              min: 1,
              message: t("agentConfig.shellCommandTimeoutMin"),
            },
          ]}
          tooltip={t("agentConfig.shellCommandTimeoutTooltip")}
          className={styles.reactAgentField}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={10}
            placeholder={t("agentConfig.shellCommandTimeoutPlaceholder")}
          />
        </Form.Item>

        <Form.Item
          label={t("agentConfig.shellCommandExecutable")}
          name="shell_command_executable"
          tooltip={t("agentConfig.shellCommandExecutableTooltip")}
          className={styles.reactAgentField}
        >
          <Input
            style={{ width: "100%" }}
            placeholder={t("agentConfig.shellCommandExecutablePlaceholder")}
            allowClear
          />
        </Form.Item>
      </div>

      <div className={styles.reactAgentSettings}>
        <ProjectDirectorySetting requestContext={requestContext} />
        <EnhancedCodeCapabilitySetting requestContext={requestContext} />
      </div>

      <Form.Item
        label={t("agentConfig.autoGenerateSessionTitle")}
        name={["auto_title_config", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.autoGenerateSessionTitleTooltip")}
      >
        <Switch />
      </Form.Item>

      <div className={styles.reactAgentRow}>
        <Form.Item
          label={t("agentConfig.memoryManagerBackend")}
          name="memory_manager_backend"
          tooltip={t("agentConfig.memoryManagerBackendTooltip")}
          className={styles.reactAgentField}
        >
          <Select
            options={MEMORY_MANAGER_BACKEND_OPTIONS}
            style={{ width: "100%" }}
          />
        </Form.Item>
      </div>
      <Alert
        type="warning"
        showIcon
        message={t("agentConfig.memoryManagerBackendRestartWarning")}
        style={{ marginBottom: 16 }}
      />
      <Form.Item
        label={t("agentConfig.planMode", "Plan Mode")}
        tooltip={t(
          "agentConfig.planModeTooltip",
          "Enable plan mode to use /plan <description> for structured task planning",
        )}
      >
        <Switch
          checked={planConfig.enabled}
          loading={planLoading}
          onChange={(checked) => updatePlanConfig({ enabled: checked })}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.planAutoMode", "Auto Plan")}
        tooltip={t(
          "agentConfig.planAutoModeTooltip",
          "Automatically create a plan for complex multi-step tasks when plan mode is enabled",
        )}
      >
        <Switch
          checked={planConfig.auto_enabled}
          loading={planLoading}
          disabled={!planConfig.enabled}
          onChange={(checked) => updatePlanConfig({ auto_enabled: checked })}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.planAutoExecute", "Auto Execute Plan")}
        tooltip={t(
          "agentConfig.planAutoExecuteTooltip",
          "Continue executing an automatically created plan without waiting for confirmation",
        )}
      >
        <Switch
          checked={planConfig.auto_execute}
          loading={planLoading}
          disabled={!planConfig.enabled || !planConfig.auto_enabled}
          onChange={(checked) => updatePlanConfig({ auto_execute: checked })}
        />
      </Form.Item>
    </Card>
  );
}
