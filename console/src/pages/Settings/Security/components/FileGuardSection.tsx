import { useAutoSave } from "@/hooks/useAutoSave";
import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Button,
  Input,
  Popconfirm,
  Tag,
  Switch,
  Alert,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Space, Spin } from "antd";
import {
  CirclePlus as PlusCircleOutlined,
  Trash2 as DeleteOutlined,
  Lock as LockOutlined,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import styles from "../index.module.less";
import local from "./SecurityEntries.module.less";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";

interface FileGuardSectionProps {
  onSave?: (handlers: {
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  }) => void;
  denyPathsActive?: boolean;
  denyPathsLoading?: boolean;
  denyPathsProtectedPaths?: string[];
  denyPathsPlatformSupported?: boolean;
  sandboxEnabled?: boolean;
  sandboxReason?: string | null;
  toggleDenyPaths?: (val: boolean) => void;
}

export function FileGuardSection({
  onSave,
  denyPathsActive = false,
  denyPathsLoading = false,
  denyPathsProtectedPaths = [],
  denyPathsPlatformSupported = false,
  sandboxEnabled = false,
  sandboxReason = null,
  toggleDenyPaths,
}: FileGuardSectionProps = {}) {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(true);
  const [allowPreviewOutsideWorkspace, setAllowPreviewOutsideWorkspace] =
    useState(false);
  const [paths, setPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const saving = false;
  const [newPath, setNewPath] = useState("");
  const [adding, setAdding] = useState(false);
  const reduced = useReducedMotion();
  const { message } = useAppMessage();
  const { schedule, flush } = useAutoSave(async () => {
    await api.updateFileGuard({ paths });
  });

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getFileGuard();
      setEnabled(data?.enabled ?? true);
      setAllowPreviewOutsideWorkspace(
        data?.allow_preview_outside_workspace ?? false,
      );
      setPaths(data?.paths ?? []);
    } catch {
      message.error(t("security.fileGuard.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, message]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleToggle = useCallback(
    async (checked: boolean) => {
      setEnabled(checked);
      try {
        await api.updateFileGuard({ enabled: checked });
        message.success(t("security.fileGuard.saveSuccess"));
      } catch {
        setEnabled(!checked);
        message.error(t("security.fileGuard.saveFailed"));
      }
    },
    [t, message],
  );

  const handlePreviewToggle = useCallback(
    async (checked: boolean) => {
      setAllowPreviewOutsideWorkspace(checked);
      try {
        await api.updateFileGuard({
          allow_preview_outside_workspace: checked,
        });
        message.success(t("security.fileGuard.saveSuccess"));
      } catch {
        setAllowPreviewOutsideWorkspace(!checked);
        message.error(t("security.fileGuard.saveFailed"));
      }
    },
    [t, message],
  );

  const handleAdd = useCallback(() => {
    const trimmed = newPath.trim();
    if (!trimmed) return;
    if (paths.includes(trimmed)) {
      message.warning(t("security.fileGuard.duplicate"));
      return;
    }
    setPaths((prev) => [...prev, trimmed]);
    schedule();
    setNewPath("");
  }, [newPath, paths, t, message, schedule]);

  const handleRemove = useCallback(
    (path: string) => {
      setPaths((prev) => prev.filter((p) => p !== path));
      schedule();
    },
    [schedule],
  );

  const handleReset = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    onSave?.({
      save: async () => {
        await flush();
      },
      reset: handleReset,
      saving,
    });
  }, [flush, handleReset, saving, onSave]);

  return (
    <>
      <Card className={styles.formCard}>
        <div className={local.settingRow}>
          <span style={{ fontWeight: 500 }}>
            {t("security.fileGuard.enableLabel")}
          </span>
          <Switch
            aria-label={t("security.fileGuard.enableLabel")}
            checked={enabled}
            onChange={handleToggle}
            disabled={loading}
          />
        </div>

        <div className={local.settingRow}>
          <div>
            <span style={{ fontWeight: 500 }}>
              {t("security.fileGuard.allowPreviewOutsideWorkspace")}
            </span>
            <div className={local.hint}>
              {t("security.fileGuard.allowPreviewOutsideWorkspaceDesc")}
            </div>
          </div>
          <Switch
            aria-label={t("security.fileGuard.allowPreviewOutsideWorkspace")}
            disabled={loading}
            checked={allowPreviewOutsideWorkspace}
            onChange={handlePreviewToggle}
          />
        </div>
      </Card>

      <section
        className={local.paths}
        aria-label={t("security.fileGuard.path")}
      >
        <div className={local.pathHeader}>
          <h3>
            {t("security.fileGuard.path")}{" "}
            <NumberFlow value={paths.length} respectMotionPreference />
          </h3>
          {!enabled && (
            <span className={local.hint}>{t("common.disabled")}</span>
          )}
          <Button
            icon={adding ? undefined : <PlusCircleOutlined size={16} />}
            disabled={!enabled || loading}
            onClick={() => setAdding((value) => !value)}
            aria-expanded={adding}
          >
            {t(adding ? "common.cancel" : "security.fileGuard.add")}
          </Button>
        </div>
        <AnimatePresence initial={false}>
          {adding && (
            <motion.div
              key="add"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={
                reduced
                  ? { duration: 0 }
                  : { type: "spring", stiffness: 360, damping: 38 }
              }
              className={local.addArea}
            >
              <Space.Compact className={local.addInput}>
                <Input
                  autoFocus
                  aria-label={t("security.fileGuard.path")}
                  value={newPath}
                  onChange={(e) => setNewPath(e.target.value)}
                  placeholder={t("security.fileGuard.inputPlaceholder")}
                  onPressEnter={handleAdd}
                  allowClear
                  disabled={!enabled}
                />
                <Button
                  type="primary"
                  onClick={handleAdd}
                  disabled={!enabled || !newPath.trim()}
                >
                  {t("security.fileGuard.add")}
                </Button>
              </Space.Compact>
            </motion.div>
          )}
        </AnimatePresence>
        <Spin spinning={loading}>
          <motion.ul className={local.pathList} layout={!reduced}>
            <AnimatePresence initial={false}>
              {paths.map((path) => (
                <motion.li
                  key={path}
                  layout={!reduced}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={
                    reduced
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 360, damping: 38 }
                  }
                  className={local.pathRow}
                >
                  <LockOutlined size={17} aria-hidden="true" />
                  <code>{path}</code>
                  <Popconfirm
                    title={t("security.fileGuard.removeConfirm")}
                    description={
                      <code className={local.confirmPath}>{path}</code>
                    }
                    onConfirm={() => handleRemove(path)}
                    okText={t("common.delete")}
                    cancelText={t("common.cancel")}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined size={16} />}
                      aria-label={`${t("common.delete")}: ${path}`}
                    />
                  </Popconfirm>
                </motion.li>
              ))}
            </AnimatePresence>
          </motion.ul>
          {!paths.length && !loading && (
            <p className={local.empty}>{t("security.fileGuard.empty")}</p>
          )}
        </Spin>
      </section>

      {denyPathsPlatformSupported &&
        sandboxEnabled &&
        sandboxReason === "unelevated" &&
        toggleDenyPaths && (
          <Card className={styles.formCard} style={{ marginTop: 16 }}>
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ margin: 0, marginBottom: 4 }}>
                <LockOutlined size="1em" style={{ marginRight: 6 }} />
                {t("security.denyPathsProtection")}
              </h3>
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: "var(--app-text-secondary)",
                }}
              >
                {t("security.denyPathsSandboxEnhancement")}
              </p>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: denyPathsActive ? 12 : 0,
              }}
            >
              <span style={{ fontWeight: 500 }}>
                {t("security.denyPathsProtectionTooltip")}
              </span>
              <Switch
                checked={denyPathsActive}
                loading={denyPathsLoading}
                onChange={(val) => toggleDenyPaths(val)}
              />
            </div>
            {denyPathsActive && (
              <Alert
                type="info"
                showIcon
                message={t("security.denyPathsActiveMessage")}
                description={
                  <>
                    <p>{t("security.denyPathsActiveDescription")}</p>
                    <div
                      style={{
                        marginTop: 8,
                        maxHeight: 120,
                        overflow: "auto",
                      }}
                    >
                      {denyPathsProtectedPaths.map((p) => (
                        <Tag key={p} style={{ marginBottom: 4 }}>
                          {p}
                        </Tag>
                      ))}
                    </div>
                  </>
                }
              />
            )}
          </Card>
        )}
    </>
  );
}
