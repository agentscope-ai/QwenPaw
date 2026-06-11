/**
 * Final step in the restore flow.
 */
import { useState, useEffect, useMemo } from "react";
import { HelpCircle } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import styles from "./RestoreBackupModal.module.less";

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

  const allBackupAgentIds = useMemo(
    () => (backupDetail ? Object.keys(backupDetail.workspace_stats) : []),
    [backupDetail],
  );

  const allAgentRows = useMemo(() => {
    return allBackupAgentIds.map((aid) => {
      const agentInfo = existingAgentMap.get(aid);
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
      message.error(
        lockedPaths.length > 0
          ? `${t("backup.restoreTargetBusy")}: ${lockedPaths.join(", ")}`
          : t("backup.restoreTargetBusy"),
      );
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

  const okDisabled =
    !confirmed || detailFailed || (detailLoading && !backupDetail);

  const trustBannerClass =
    trustState === false
      ? "border-green-200 bg-green-50 text-green-800 dark-mode:border-green-800 dark-mode:bg-green-950 dark-mode:text-green-200"
      : trustState === true
      ? "border-yellow-200 bg-yellow-50 text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200"
      : "border-blue-200 bg-blue-50 text-blue-800 dark-mode:border-blue-800 dark-mode:bg-blue-950 dark-mode:text-blue-200";

  return (
    <>
      <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("backup.restoreTitle")}</DialogTitle>
          </DialogHeader>

          <div className={styles.modalBody}>
            <div className={styles.backupInfoSection}>
              <span className="text-sm font-semibold">{backup.name}</span>
              {backup.description && (
                <div
                  className={`${styles.backupDescription} text-sm text-muted-foreground`}
                >
                  {backup.description}
                </div>
              )}
            </div>

            <div
              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${trustBannerClass} ${styles.trustBanner}`}
            >
              <span>
                {trustState === false ? "✓" : trustState === true ? "⚠" : "ℹ"}
              </span>
              <div>
                {trustState === false
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
                    })}
              </div>
            </div>

            {detailFailed && (
              <div
                className={`flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 ${styles.fullRestoreAlert}`}
              >
                <span>✕</span>
                {t("backup.detailLoadFailed")}
              </div>
            )}

            {hasNewAgents && !detailFailed && (
              <div className={styles.workspaceDirSection}>
                <div
                  className={`${styles.workspaceDirLabel} flex items-center gap-1 text-sm font-medium`}
                >
                  {t("backup.defaultWorkspaceDir")}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <HelpCircle
                        size={14}
                        className="cursor-help text-muted-foreground"
                      />
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("backup.defaultWorkspaceDirHint")}
                    </TooltipContent>
                  </Tooltip>
                </div>
                <Input
                  value={defaultWorkspaceDir}
                  onChange={(e) => setDefaultWorkspaceDir(e.target.value)}
                  placeholder={t("backup.defaultWorkspaceDirPlaceholder")}
                />
              </div>
            )}

            <Separator className={styles.dividerTop} />

            <div className={styles.restoreModeSection}>
              <div
                className={`${styles.restoreModeLabel} text-sm font-medium mb-2`}
              >
                {t("backup.restoreMode")}
              </div>
              <div className={`${styles.radioGroup} flex flex-col gap-2`}>
                {(["full", "custom"] as const).map((mode) => (
                  <label
                    key={mode}
                    className={`flex cursor-pointer items-start gap-2 ${
                      mode === "full" && !fullBackup
                        ? "opacity-50 cursor-not-allowed"
                        : ""
                    }`}
                  >
                    <input
                      type="radio"
                      name="restoreMode"
                      value={mode}
                      checked={restoreMode === mode}
                      disabled={mode === "full" && !fullBackup}
                      onChange={() => setRestoreMode(mode)}
                      className="mt-1 accent-primary"
                    />
                    <span>
                      <span className="text-sm font-medium">
                        {mode === "full"
                          ? t("backup.restoreModeFull")
                          : t("backup.restoreModeCustom")}
                        {mode === "full" && !fullBackup && (
                          <Badge variant="secondary" className="ml-2 text-xs">
                            {t("backup.restoreModeFullDisabled")}
                          </Badge>
                        )}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {mode === "full"
                          ? t("backup.restoreModeFullDesc")
                          : t("backup.restoreModeCustomDesc")}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div className={styles.strategySection}>
              <div
                className={`${styles.strategyLabel} text-sm font-medium mb-2`}
              >
                {t("backup.restoreStrategy", {
                  defaultValue: "Restore strategy",
                })}
              </div>
              <div className="flex flex-col gap-2">
                {(["preserve", "restore"] as const).map((strategy) => (
                  <label
                    key={strategy}
                    className="flex cursor-pointer items-start gap-2"
                  >
                    <input
                      type="radio"
                      name="restoreStrategy"
                      value={strategy}
                      checked={restoreStrategy === strategy}
                      onChange={() => setRestoreStrategy(strategy)}
                      className="mt-1 accent-primary"
                    />
                    <span>
                      <span className="text-sm font-medium">
                        {strategy === "preserve"
                          ? t("backup.restoreStrategyPreserve", {
                              defaultValue: "Preserve local security and MCP",
                            })
                          : t("backup.restoreStrategyRestore", {
                              defaultValue:
                                "Restore these settings from backup",
                            })}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {strategy === "preserve"
                          ? t("backup.restoreStrategyPreserveDesc", {
                              defaultValue:
                                "Keep this instance's security guards and MCP configuration.",
                            })
                          : t("backup.restoreStrategyRestoreDesc", {
                              defaultValue:
                                "Use the backup's security and MCP configuration.",
                            })}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {restoreMode === "full" && (
              <div
                className={`flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200 ${styles.fullRestoreAlert}`}
              >
                <span>⚠</span>
                {t("backup.restoreFullWarning")}
              </div>
            )}

            {restoreMode === "custom" && (
              <div className={styles.customOptions}>
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
                  <div
                    className={`${styles.checkboxRow} flex items-center gap-2`}
                  >
                    <Checkbox
                      id="global-config"
                      checked={globalConfig}
                      onCheckedChange={(c) => setGlobalConfig(!!c)}
                    />
                    <Label htmlFor="global-config" className="cursor-pointer">
                      {t("backup.scopeGlobalConfig")}
                    </Label>
                  </div>
                )}

                {backup.scope.include_skill_pool && (
                  <div
                    className={`${styles.checkboxRow} flex items-center gap-2`}
                  >
                    <Checkbox
                      id="skill-pool"
                      checked={includeSkillPool}
                      onCheckedChange={(c) => setIncludeSkillPool(!!c)}
                    />
                    <Label htmlFor="skill-pool" className="cursor-pointer">
                      {t("backup.scopeSkillPool")}
                    </Label>
                  </div>
                )}

                {backup.scope.include_secrets && (
                  <div className={styles.checkboxRow}>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="secrets"
                        checked={includeSecrets}
                        onCheckedChange={(c) => setIncludeSecrets(!!c)}
                      />
                      <Label htmlFor="secrets" className="cursor-pointer">
                        {t("backup.scopeSecrets")}
                      </Label>
                    </div>
                    <div className="text-xs text-muted-foreground ml-6">
                      {t("backup.scopeSecretsHint")}
                    </div>
                  </div>
                )}
              </div>
            )}

            <Separator className={styles.dividerBottom} />

            {restoreMode === "custom" && (
              <div
                className={`flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200 ${styles.customRestoreAlert}`}
              >
                <span>⚠</span>
                <ul className="list-disc ml-4">
                  <li>{t("backup.restoreWarningModify")}</li>
                  <li>{t("backup.restoreWarningRestart")}</li>
                </ul>
              </div>
            )}

            <div className="flex items-center gap-2">
              <Checkbox
                id="confirm-restore"
                checked={confirmed}
                onCheckedChange={(c) => setConfirmed(!!c)}
              />
              <Label htmlFor="confirm-restore" className="cursor-pointer">
                {t("backup.restoreConfirm")}
              </Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={onClose} disabled={loading}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={handleOk}
              disabled={okDisabled || loading}
            >
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
