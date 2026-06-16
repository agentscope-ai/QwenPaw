import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Switch } from "@agentscope-ai/design";
import { Modal, message } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import type { IntegrityProtectionSettings } from "@/api/modules/security";
import { useFileBaselineDriftWatch } from "../hooks/useFileBaselineDriftWatch";
import type { FileBaselineProtectionSettings } from "../api/client";
import styles from "@/pages/Settings/Security/index.module.less";
import { FileBaselineProtectionFileList } from "./FileBaselineProtectionFileList";

interface FileBaselineProtectionContextValue {
  fileBaselineSettings: FileBaselineProtectionSettings | null;
  fileBaselineSwitchLoading: boolean;
  pathsSaving: boolean;
  protectedPaths: string[];
  loadFileBaselineSettings: () => Promise<void>;
  onFileBaselineSwitchChange: (checked: boolean) => Promise<void>;
  toggleProtectedPath: (path: string, enabled: boolean) => Promise<void>;
}

const FileBaselineProtectionContext =
  createContext<FileBaselineProtectionContextValue | null>(null);

function useFileBaselineProtectionContext(): FileBaselineProtectionContextValue {
  const value = useContext(FileBaselineProtectionContext);
  if (!value) {
    throw new Error("FileBaselineProtection components must be used within Provider");
  }
  return value;
}

export interface FileBaselineProtectionProviderProps {
  children: ReactNode;
  onIntegritySettingsSync?: (settings: IntegrityProtectionSettings) => void;
}

export function FileBaselineProtectionProvider({
  children,
  onIntegritySettingsSync,
}: FileBaselineProtectionProviderProps) {
  const { t } = useTranslation();
  const [fileBaselineSettings, setFileBaselineSettings] =
    useState<FileBaselineProtectionSettings | null>(null);
  const [fileBaselineSwitchLoading, setFileBaselineSwitchLoading] = useState(false);
  const [pathsSaving, setPathsSaving] = useState(false);

  const loadFileBaselineSettings = useCallback(async () => {
    const settings = await api.getFileBaselineProtectionSettings();
    setFileBaselineSettings(settings);
  }, []);

  useFileBaselineDriftWatch(
    (event) => {
      if (event.type === "file_baseline_updated") {
        void loadFileBaselineSettings();
      }
    },
    Boolean(fileBaselineSettings?.enabled),
  );

  const persistProtectedPaths = useCallback(
    async (nextPaths: string[]) => {
      setPathsSaving(true);
      try {
        const updated = await api.updateFileBaselineProtectionSettings({
          protected_targets: nextPaths,
        });
        setFileBaselineSettings(updated);
        const aggregate = await api.getIntegrityProtectionSettings();
        onIntegritySettingsSync?.(aggregate);
      } catch {
        message.error(t("security.integrityProtection.loadFailed"));
        throw new Error("protected paths update failed");
      } finally {
        setPathsSaving(false);
      }
    },
    [onIntegritySettingsSync, t],
  );

  const toggleProtectedPath = useCallback(
    async (path: string, enabled: boolean) => {
      const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "").trim();
      if (!normalized) {
        return;
      }
      const current = fileBaselineSettings?.protected_targets ?? [];
      if (enabled) {
        if (current.includes(normalized)) {
          return;
        }
        await persistProtectedPaths([...current, normalized]);
        message.success(t("security.integrityProtection.protectedPathAddSuccess"));
      } else {
        if (!current.includes(normalized)) {
          return;
        }
        await persistProtectedPaths(current.filter((item) => item !== normalized));
        message.success(t("security.integrityProtection.protectedPathRemoveSuccess"));
      }
      await loadFileBaselineSettings();
    },
    [fileBaselineSettings?.protected_targets, loadFileBaselineSettings, persistProtectedPaths, t],
  );

  const applyFileBaselineToggle = useCallback(
    async (checked: boolean, confirmationPhrase?: string) => {
      if (checked && (fileBaselineSettings?.protected_targets?.length ?? 0) === 0) {
        message.warning(t("security.integrityProtection.protectedPathEmpty"));
        return;
      }
      setFileBaselineSwitchLoading(true);
      try {
        const updated = await api.updateFileBaselineProtectionSettings({
          enabled: checked,
          confirmation_phrase: confirmationPhrase,
        });
        setFileBaselineSettings(updated);
        const aggregate = await api.getIntegrityProtectionSettings();
        onIntegritySettingsSync?.(aggregate);
        await loadFileBaselineSettings();
        message.success(
          checked
            ? t("security.integrityProtection.fileBaselineEnableSuccess")
            : t("security.integrityProtection.fileBaselineDisableSuccess"),
        );
      } catch {
        message.error(t("security.integrityProtection.loadFailed"));
        throw new Error("file baseline toggle failed");
      } finally {
        setFileBaselineSwitchLoading(false);
      }
    },
    [fileBaselineSettings?.protected_targets, loadFileBaselineSettings, onIntegritySettingsSync, t],
  );

  const onFileBaselineSwitchChange = useCallback(
    async (checked: boolean) => {
      if (checked) {
        if (fileBaselineSettings?.baseline_cleared_at) {
          Modal.confirm({
            title: t("security.integrityProtection.fileBaselineReestablishTitle"),
            content: t("security.integrityProtection.fileBaselineReestablishBody"),
            okText: t("common.confirm"),
            cancelText: t("common.cancel"),
            onOk: async () => {
              await applyFileBaselineToggle(
                true,
                t(
                  "security.integrityProtection.confirmReestablishFileBaselinePhrase",
                ),
              );
            },
          });
          return;
        }
      } else if ((fileBaselineSettings?.open_alert_count ?? 0) > 0) {
        Modal.confirm({
          title: t("security.integrityProtection.fileBaselineDisableWarningTitle"),
          content: t("security.integrityProtection.disableWithOpenDriftsWarning"),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            await applyFileBaselineToggle(false);
          },
        });
        return;
      }

      await applyFileBaselineToggle(checked);
    },
    [applyFileBaselineToggle, fileBaselineSettings, t],
  );

  const protectedPaths = fileBaselineSettings?.protected_targets ?? [];

  const value = useMemo(
    () => ({
      fileBaselineSettings,
      fileBaselineSwitchLoading,
      pathsSaving,
      protectedPaths,
      loadFileBaselineSettings,
      onFileBaselineSwitchChange,
      toggleProtectedPath,
    }),
    [
      fileBaselineSettings,
      fileBaselineSwitchLoading,
      loadFileBaselineSettings,
      onFileBaselineSwitchChange,
      pathsSaving,
      protectedPaths,
      toggleProtectedPath,
    ],
  );

  return (
    <FileBaselineProtectionContext.Provider value={value}>
      {children}
    </FileBaselineProtectionContext.Provider>
  );
}

export function FileBaselineProtectionSwitchRow() {
  const { t } = useTranslation();
  const { fileBaselineSettings, fileBaselineSwitchLoading, onFileBaselineSwitchChange } =
    useFileBaselineProtectionContext();

  return (
    <div className={styles.integrityConfigItem}>
      <span className={styles.skillScannerLabel}>
        {t("security.integrityProtection.fileBaselineProtection")}
      </span>
      <Switch
        checked={fileBaselineSettings?.enabled ?? false}
        loading={fileBaselineSwitchLoading}
        onChange={(checked) => {
          void onFileBaselineSwitchChange(checked);
        }}
      />
    </div>
  );
}

export { FileBaselineProtectionFileList } from "./FileBaselineProtectionFileList";

/** @deprecated Use FileBaselineProtectionFileList */
export function FileBaselineProtectionProtectedPaths() {
  return <FileBaselineProtectionFileList />;
}

export { useFileBaselineProtectionContext };
