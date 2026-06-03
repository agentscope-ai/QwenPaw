/**
 * Final step in the restore flow: lets the user pick full or custom restore mode,
 * choose which agents / config items to include, and confirm before applying.
 *
 * On open it fetches the backup detail (real agent list from workspace_stats).
 * If the detail fetch fails the modal shows an error and disables the OK button,
 * since we need workspace_stats to build the explicit agent_ids list.
 * A "confirmed" checkbox gates the submit button to prevent accidental data loss.
 */
import { useState, useEffect, useMemo } from "react";
import {
  Modal,
  Checkbox,
  Radio,
  Alert,
  Input,
  Tag,
  Divider,
  Typography,
  Tooltip,
  Space,
} from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type {
  BackupMeta,
  BackupDetail,
  RestoreBackupRequest,
} from "@/api/types/backup";
import type { AgentSummary } from "@/api/types/agents";
import { parseErrorDetail } from "@/utils/error";
import { isFullBackup } from "../shared/scope";
import BackupTrustDialog from "../trust/BackupTrustDialog";
import {
  trustModeFromErrorCode,
  type BackupTrustMode,
} from "../trust/trustErrors";
import RestoreAgentTable from "./RestoreAgentTable";
import styles from "./RestoreBackupModal.module.less";

const { Text } = Typography;

interface Props {
  open: boolean;
  backup: BackupMeta;
  agents: AgentSummary[];
  onClose: () => void;
  onSuccess: () => void;
}

type RestoreMode = "full" | "custom";
type RestoreStrategy = "preserve" | "restore";
type TrustPrompt = {
  mode: BackupTrustMode;
  request: RestoreBackupRequest;
};

export default function RestoreBackupModal({
  open,
  backup,
  agents,
  onClose,
  onSuccess,
}: Props) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(false);

  const fullBackup = isFullBackup(backup.scope);
  const [restoreMode, setRestoreMode] = useState<RestoreMode>(
    fullBackup ? "full" : "custom",
  );
  // Foreign/legacy backups default to preserving local security and MCP
  // controls; local backups can restore them unless the user changes this.
  const [restoreStrategy, setRestoreStrategy] =
    useState<RestoreStrategy>("preserve");

  const [backupDetail, setBackupDetail] = useState<BackupDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailFailed, setDetailFailed] = useState(false);

  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [globalConfig, setGlobalConfig] = useState(
    backup.scope.include_global_config,
  );
  const [includeSkillPool, setIncludeSkillPool] = useState(
    backup.scope.include_skill_pool,
  );
  const [includeSecrets, setIncludeSecrets] = useState(
    backup.scope.include_secrets,
  );
  const [defaultWorkspaceDir, setDefaultWorkspaceDir] = useState("");
  const [includeAgents, setIncludeAgents] = useState(
    backup.scope.include_agents,
  );
  const [confirmed, setConfirmed] = useState(false);
  const [trustPrompt, setTrustPrompt] = useState<TrustPrompt | null>(null);
  const [trustLoading, setTrustLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDetailLoading(true);
    setDetailFailed(false);
    setBackupDetail(null);
    api
      .getBackup(backup.id)
      .then((detail) => {
        setBackupDetail(detail);
        setSelectedAgents(Object.keys(detail.workspace_stats));
      })
      .catch(() => {
        setDetailFailed(true);
        message.error(t("backup.detailLoadFailed"));
      })
      .finally(() => setDetailLoading(false));
    // keying on backup.id is intentional: re-fetch when a different backup is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, backup.id]);

  useEffect(() => {
    if (!open) return;
    setRestoreMode(fullBackup ? "full" : "custom");
    setRestoreStrategy(
      backup.accepted_via_trust === false ? "restore" : "preserve",
    );
    setConfirmed(false);
    setTrustPrompt(null);
  }, [open, backup.id, backup.accepted_via_trust, fullBackup]);

  const existingAgentMap = useMemo(
    () => new Map(agents.map((a) => [a.id, a])),
    [agents],
  );

  // All agent IDs present in the backup (only available after detail loads).
  const allBackupAgentIds = useMemo(
    () => (backupDetail ? Object.keys(backupDetail.workspace_stats) : []),
    [backupDetail],
  );

  const allAgentRows = useMemo(() => {
    return allBackupAgentIds.map((aid) => {
      const agentInfo = existingAgentMap.get(aid);
      // For new (not-yet-existing) agents we can't look up the name from
      // /api/agents, so fall back to the name embedded inside the backup's
      // workspace/agent.json (exposed via workspace_stats[aid].name).
      const backupName = backupDetail?.workspace_stats?.[aid]?.name;
      return {
        key: aid,
        aid,
        name: agentInfo?.name ?? backupName ?? aid,
        isExisting: !!agentInfo,
        currentWorkspaceDir: agentInfo?.workspace_dir ?? "",
      };
    });
  }, [allBackupAgentIds, existingAgentMap, backupDetail]);

  const newCount = useMemo(
    () => allAgentRows.filter((r) => !r.isExisting).length,
    [allAgentRows],
  );
  const hasNewAgents = newCount > 0;

  const selectedExistingCount = useMemo(
    () => selectedAgents.filter((id) => existingAgentMap.has(id)).length,
    [selectedAgents, existingAgentMap],
  );
  const selectedNewCount = useMemo(
    () => selectedAgents.filter((id) => !existingAgentMap.has(id)).length,
    [selectedAgents, existingAgentMap],
  );

  const buildRestoreRequest = (): RestoreBackupRequest => {
    const isFull = restoreMode === "full";
    const doIncludeAgents = isFull ? true : includeAgents;
    const agent_ids = isFull
      ? allBackupAgentIds
      : includeAgents
      ? selectedAgents
      : [];

    return {
      mode: restoreMode,
      include_agents: doIncludeAgents,
      agent_ids,
      include_global_config: isFull ? true : globalConfig,
      include_secrets: isFull ? true : includeSecrets,
      include_skill_pool: isFull ? true : includeSkillPool,
      default_workspace_dir: defaultWorkspaceDir.trim() || null,
      // Backend overlays local security/MCP config after the selected restore
      // mode has built its config payload.
      preserve_local_protected_config: restoreStrategy === "preserve",
    };
  };

  const finishRestore = async (request: RestoreBackupRequest) => {
    const response = await api.restoreBackup(backup.id, request);
    const preserved = response.preserved_local_keys ?? [];
    if (preserved.length > 0) {
      message.success(
        t("backup.restoreSuccessPreserved", {
          defaultValue:
            "Backup restored successfully. Preserved local settings: {{keys}}. Please restart the service.",
          keys: preserved.join(", "),
        }),
      );
    } else {
      message.success(t("backup.restoreSuccess"));
    }
    onSuccess();
    onClose();
  };

  const showRestoreFailure = (detail: Record<string, unknown> | null) => {
    if (detail?.code === "restore_target_busy") {
      const lockedPaths = Array.isArray(detail.locked_paths)
        ? detail.locked_paths.filter(
            (path): path is string => typeof path === "string" && !!path,
          )
        : [];

      message.error({
        content: (
          <div className={styles.restoreErrorMessage}>
            <div>{t("backup.restoreTargetBusy")}</div>
            {lockedPaths.length > 0 && (
              <div className={styles.lockedPathList}>
                {lockedPaths.map((path) => (
                  <div key={path} className={styles.lockedPath}>
                    {path}
                  </div>
                ))}
              </div>
            )}
          </div>
        ),
        duration: 8,
      });
      return;
    }

    message.error(t("backup.restoreFailed"));
  };

  const handleOk = async () => {
    const request = buildRestoreRequest();
    setLoading(true);
    try {
      await finishRestore(request);
    } catch (err: unknown) {
      const detail = parseErrorDetail(err);
      const trustMode = trustModeFromErrorCode(detail?.code);
      if (trustMode) {
        setTrustPrompt({ mode: trustMode, request });
      } else {
        showRestoreFailure(detail);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleTrustConfirm = async () => {
    if (!trustPrompt) return;
    setTrustLoading(true);
    try {
      await finishRestore({
        ...trustPrompt.request,
        trust_mode: trustPrompt.mode,
      });
      setTrustPrompt(null);
    } catch (err: unknown) {
      showRestoreFailure(parseErrorDetail(err));
    } finally {
      setTrustLoading(false);
    }
  };

  const trustState =
    backupDetail?.accepted_via_trust ?? backup.accepted_via_trust ?? null;

  const summaryText =
    restoreMode === "custom" &&
    (selectedExistingCount > 0 || selectedNewCount > 0)
      ? t("backup.restoreCustomSummary", {
          existing: selectedExistingCount,
          added: selectedNewCount,
        })
      : null;

  // OK is disabled when detail hasn't loaded (we need workspace_stats to build agent_ids),
  // or when the user hasn't confirmed the destructive action.
  const okDisabled =
    !confirmed || detailFailed || (detailLoading && !backupDetail);

  return (
    <>
      <Modal
        title={t("backup.restoreTitle")}
        open={open}
        onCancel={onClose}
        onOk={handleOk}
        confirmLoading={loading}
        okButtonProps={{ disabled: okDisabled, danger: true }}
        okText={t("common.confirm")}
        destroyOnHidden
        centered
        width={680}
      >
        <div className={styles.modalBody}>
          <div className={styles.backupInfoSection}>
            <Text strong style={{ fontSize: 14 }}>
              {backup.name}
            </Text>
            {backup.description && (
              <div className={styles.backupDescription}>
                {backup.description}
              </div>
            )}
          </div>

          <Alert
            showIcon
            type={
              trustState === false
                ? "success"
                : trustState === true
                ? "warning"
                : "info"
            }
            message={
              trustState === false
                ? t("backup.trustLocalBanner", {
                    defaultValue: "Local backup - full restore by default",
                  })
                : trustState === true
                ? t("backup.trustForeignBanner", {
                    defaultValue:
                      "Imported backup - local security and MCP are preserved by default",
                  })
                : t("backup.trustLegacyBanner", {
                    defaultValue:
                      "Legacy backup - trust confirmation is required before restore",
                  })
            }
            className={styles.trustBanner}
          />

          {detailFailed && (
            <Alert
              type="error"
              showIcon
              message={t("backup.detailLoadFailed")}
              className={styles.fullRestoreAlert}
            />
          )}

          {hasNewAgents && !detailFailed && (
            <div className={styles.workspaceDirSection}>
              <div className={styles.workspaceDirLabel}>
                {t("backup.defaultWorkspaceDir")}
                <Tooltip title={t("backup.defaultWorkspaceDirHint")}>
                  <QuestionCircleOutlined className={styles.hintIcon} />
                </Tooltip>
              </div>
              <Input
                value={defaultWorkspaceDir}
                onChange={(e) => setDefaultWorkspaceDir(e.target.value)}
                placeholder={t("backup.defaultWorkspaceDirPlaceholder")}
              />
            </div>
          )}

          <Divider className={styles.dividerTop} />

          <div className={styles.restoreModeSection}>
            <div className={styles.restoreModeLabel}>
              {t("backup.restoreMode")}
            </div>
            <Radio.Group
              value={restoreMode}
              onChange={(e) => setRestoreMode(e.target.value)}
              className={styles.radioGroup}
            >
              <Radio value="full" disabled={!fullBackup}>
                <div className={styles.radioOption}>
                  <div className={styles.radioOptionHeader}>
                    <Text strong>{t("backup.restoreModeFull")}</Text>
                    {!fullBackup && (
                      <Tag color="default" className={styles.radioDisabledTag}>
                        {t("backup.restoreModeFullDisabled")}
                      </Tag>
                    )}
                  </div>
                  <Text type="secondary" className={styles.radioDesc}>
                    {t("backup.restoreModeFullDesc")}
                  </Text>
                </div>
              </Radio>
              <Radio value="custom">
                <div className={styles.radioOption}>
                  <Text strong>{t("backup.restoreModeCustom")}</Text>
                  <Text type="secondary" className={styles.radioDesc}>
                    {t("backup.restoreModeCustomDesc")}
                  </Text>
                </div>
              </Radio>
            </Radio.Group>
          </div>

          <div className={styles.strategySection}>
            <div className={styles.strategyLabel}>
              {t("backup.restoreStrategy", {
                defaultValue: "Restore strategy",
              })}
            </div>
            <Radio.Group
              value={restoreStrategy}
              onChange={(e) => setRestoreStrategy(e.target.value)}
              className={styles.radioGroup}
            >
              <Radio value="preserve">
                <div className={styles.radioOption}>
                  <Text strong>
                    {t("backup.restoreStrategyPreserve", {
                      defaultValue: "Preserve local security and MCP",
                    })}
                  </Text>
                  <Text type="secondary" className={styles.radioDesc}>
                    {t("backup.restoreStrategyPreserveDesc", {
                      defaultValue:
                        "Keep this instance's security guards and MCP configuration.",
                    })}
                  </Text>
                </div>
              </Radio>
              <Radio value="restore">
                <div className={styles.radioOption}>
                  <Text strong>
                    {t("backup.restoreStrategyRestore", {
                      defaultValue: "Restore these settings from backup",
                    })}
                  </Text>
                  <Text type="secondary" className={styles.radioDesc}>
                    {t("backup.restoreStrategyRestoreDesc", {
                      defaultValue:
                        "Use the backup's security and MCP configuration.",
                    })}
                  </Text>
                </div>
              </Radio>
            </Radio.Group>
          </div>

          {restoreMode === "full" && (
            <Alert
              type="warning"
              showIcon
              message={t("backup.restoreFullWarning")}
              className={styles.fullRestoreAlert}
            />
          )}

          {restoreMode === "custom" && (
            <Space
              direction="vertical"
              size={0}
              className={styles.customOptions}
            >
              {backup.scope.include_agents && (
                <RestoreAgentTable
                  allAgentRows={allAgentRows}
                  selectedAgents={selectedAgents}
                  onSelectionChange={setSelectedAgents}
                  detailLoading={detailLoading}
                  defaultWorkspaceDir={defaultWorkspaceDir}
                  includeAgents={includeAgents}
                  onIncludeAgentsChange={setIncludeAgents}
                  summaryText={summaryText}
                />
              )}

              {backup.scope.include_global_config && (
                <div className={styles.checkboxRow}>
                  <Checkbox
                    checked={globalConfig}
                    onChange={(e) => setGlobalConfig(e.target.checked)}
                  >
                    {t("backup.scopeGlobalConfig")}
                  </Checkbox>
                </div>
              )}

              {backup.scope.include_skill_pool && (
                <div className={styles.checkboxRow}>
                  <Checkbox
                    checked={includeSkillPool}
                    onChange={(e) => setIncludeSkillPool(e.target.checked)}
                  >
                    {t("backup.scopeSkillPool")}
                  </Checkbox>
                </div>
              )}

              {backup.scope.include_secrets && (
                <div className={styles.checkboxRow}>
                  <Checkbox
                    checked={includeSecrets}
                    onChange={(e) => setIncludeSecrets(e.target.checked)}
                  >
                    {t("backup.scopeSecrets")}
                  </Checkbox>
                  <div className={styles.secretsHint}>
                    {t("backup.scopeSecretsHint")}
                  </div>
                </div>
              )}
            </Space>
          )}

          <Divider className={styles.dividerBottom} />

          {restoreMode === "custom" && (
            <Alert
              type="warning"
              showIcon
              message={
                <ul className={styles.restoreWarningList}>
                  <li>{t("backup.restoreWarningModify")}</li>
                  <li>{t("backup.restoreWarningRestart")}</li>
                </ul>
              }
              className={styles.customRestoreAlert}
            />
          )}

          <Checkbox
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          >
            {t("backup.restoreConfirm")}
          </Checkbox>
        </div>
      </Modal>
      <BackupTrustDialog
        open={!!trustPrompt}
        mode={trustPrompt?.mode ?? "legacy"}
        backupName={backup.name}
        confirmLoading={trustLoading}
        onConfirm={handleTrustConfirm}
        onCancel={() => setTrustPrompt(null)}
      />
    </>
  );
}
