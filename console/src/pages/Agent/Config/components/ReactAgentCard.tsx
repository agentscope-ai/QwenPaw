import { SettingsField } from "@/components/interaction/SettingsField";
import { NumberSlider } from "@/components/interaction/NumberSlider";
import { Collapse } from "antd";
import {
  Button,
  Form,
  Input,
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
import TimezoneAtlas from "./TimezoneAtlas";
import { useMemoryBackends } from "../../../../plugins/memoryBackends";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  useCodingMode,
  useCodingModeStore,
} from "../../../../stores/codingModeStore";
import { useProjectDirectoryStore } from "../../../../stores/projectDirectoryStore";
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
  const setProjectDir = useProjectDirectoryStore(
    (state) => state.setProjectDir,
  );
  const [projectDirs, setProjectDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const primaryDir = projectDirs[0] ?? "";
  const primaryName =
    primaryDir
      .replace(/[\\/]+$/, "")
      .split(/[\\/]/)
      .pop() || primaryDir;
  const extraDirCount = Math.max(0, projectDirs.length - 1);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const defaults = await projectDirectoryApi.getDirs();
      const dirs = defaults.project_dirs.length
        ? defaults.project_dirs.map((entry) => entry.path)
        : [defaults.workspace_dir];
      setProjectDirs(dirs);
      setProjectDir(
        selectedAgent,
        defaults.source === "workspace_fallback"
          ? null
          : defaults.project_dirs[0]?.path ?? null,
      );
    } finally {
      setLoading(false);
    }
  }, [selectedAgent, setProjectDir]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <>
      <SettingsField
        label={t("agentConfig.projectDirectoryTitle")}
        tooltip={t("agentConfig.projectDirectoryDescription")}
        className={styles.reactAgentWideField}
      >
        <div className={styles.projectDirectorySetting}>
          <FolderOpen size={17} />
          <div className={styles.projectDirectoryPaths}>
            <strong>{primaryName}</strong>
            <span title={primaryDir}>{primaryDir}</span>
          </div>
          {extraDirCount > 0 && (
            <em
              className={styles.projectDirectoryCount}
              title={t("projectDirectory.countTitle")}
            >
              +{extraDirCount}
            </em>
          )}
          {loading ? (
            <LoaderCircle className={styles.spin} size={16} />
          ) : (
            <Button size="small" onClick={() => setModalOpen(true)}>
              {t("agentConfig.changeProjectDirectory")}
            </Button>
          )}
        </div>
      </SettingsField>
      <ProjectSelectModal
        agentId={selectedAgent}
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
    <SettingsField
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
    </SettingsField>
  );
}

export function ReactAgentCard({
  language,
  savingLang,
  onLanguageChange,
  timezone,
  onTimezoneChange,
}: ReactAgentCardProps) {
  const memoryBackends = useMemoryBackends();
  const selectedMemoryBackend =
    Form.useWatch("memory_manager_backend") || "remelight";
  const memoryBackendOptions = memoryBackends.map((backend) => ({
    value: backend.id,
    label:
      backend.available === false
        ? `${backend.label} (unavailable)`
        : backend.label,
    disabled: backend.available === false,
  }));
  if (!memoryBackends.some((backend) => backend.id === selectedMemoryBackend)) {
    memoryBackendOptions.push({
      value: selectedMemoryBackend,
      label: `${selectedMemoryBackend} (plugin unavailable)`,
      disabled: true,
    });
  }
  const { t } = useTranslation();

  return (
    <Card className={styles.formCard}>
      <div className={styles.reactAgentRow}>
        <SettingsField
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
        </SettingsField>

        <SettingsField
          label={t("agentConfig.timezone")}
          tooltip={t("agentConfig.timezoneTooltip")}
          className={styles.reactAgentField}
        >
          <TimezoneAtlas value={timezone} onChange={onTimezoneChange} />
        </SettingsField>
      </div>

      <div className={styles.reactAgentSettings}>
        <ProjectDirectorySetting />
        <EnhancedCodeCapabilitySetting />
      </div>

      <SettingsField
        label={t("agentConfig.autoGenerateSessionTitle")}
        name={["auto_title_config", "enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.autoGenerateSessionTitleTooltip")}
      >
        <Switch />
      </SettingsField>

      <Collapse
        ghost
        items={[
          {
            key: "runtime",
            label: t("agentConfig.advancedRuntime", "Advanced runtime"),
            forceRender: true,
            children: (
              <>
                <div className={styles.reactAgentRow}>
                  {" "}
                  <SettingsField
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
                    <NumberSlider
                      min={1}
                      max={600}
                      step={1}
                      label={t("agentConfig.shellCommandTimeout")}
                    />
                  </SettingsField>
                  <SettingsField
                    label={t("agentConfig.shellCommandExecutable")}
                    name="shell_command_executable"
                    tooltip={t("agentConfig.shellCommandExecutableTooltip")}
                    className={styles.reactAgentField}
                  >
                    <Input
                      style={{ width: "100%" }}
                      placeholder={t(
                        "agentConfig.shellCommandExecutablePlaceholder",
                      )}
                      allowClear
                    />
                  </SettingsField>
                </div>{" "}
                <div className={styles.reactAgentRow}>
                  <SettingsField
                    label={t("agentConfig.memoryManagerBackend")}
                    name="memory_manager_backend"
                    tooltip={t("agentConfig.memoryManagerBackendTooltip")}
                    className={styles.reactAgentField}
                  >
                    <Select
                      options={memoryBackendOptions}
                      style={{ width: "100%" }}
                    />
                  </SettingsField>
                </div>
                <Alert
                  type="warning"
                  showIcon
                  message={t("agentConfig.memoryManagerBackendRestartWarning")}
                  style={{ marginBottom: 16 }}
                />
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
