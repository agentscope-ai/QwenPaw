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
import { codingModeApi } from "../../../../api/modules/codingMode";
import { projectDirectoryApi } from "../../../../api/modules/projectDirectory";
import ProjectSelectModal from "../../../../components/ProjectSelectModal";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import { MEMORY_MANAGER_BACKEND_OPTIONS } from "../../../../constants/backendMappings";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  useCodingMode,
  useCodingModeStore,
} from "../../../../stores/codingModeStore";
import {
  useProjectDirectoryStore,
  useProjectDir,
} from "../../../../stores/projectDirectoryStore";
import styles from "../index.module.less";

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
}

function ProjectDirectorySetting() {
  const { t } = useTranslation();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const { projectDir } = useProjectDir();
  const setProjectDir = useProjectDirectoryStore(
    (state) => state.setProjectDir,
  );
  const [projectName, setProjectName] = useState("");
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const project = await projectDirectoryApi.get();
      setProjectDir(
        selectedAgent,
        project.is_workspace_default ? null : project.path,
      );
      setProjectName(project.name);
    } finally {
      setLoading(false);
    }
  }, [selectedAgent, setProjectDir]);

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
      />
    </>
  );
}

function EnhancedCodeCapabilitySetting() {
  const { t } = useTranslation();
  const { codingMode } = useCodingMode();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const setCodingMode = useCodingModeStore((state) => state.setCodingMode);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const mode = await codingModeApi.get();
      setCodingMode(selectedAgent, mode.enabled);
    } finally {
      setLoading(false);
    }
  }, [selectedAgent, setCodingMode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (enabled: boolean) => {
    setSaving(true);
    try {
      const result = await codingModeApi.toggle(enabled);
      setCodingMode(selectedAgent, result.enabled);
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
}: ReactAgentCardProps) {
  const { t } = useTranslation();

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
        <ProjectDirectorySetting />
        <EnhancedCodeCapabilitySetting />
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
    </Card>
  );
}
