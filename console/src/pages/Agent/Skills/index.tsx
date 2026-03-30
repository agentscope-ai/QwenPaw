import { useEffect, useRef, useState } from "react";
import { Button, Form, Tooltip, message } from "@agentscope-ai/design";
import {
  AppstoreAddOutlined,
  DownloadOutlined,
  ImportOutlined,
  PlusOutlined,
  SwapOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type {
  MarketError,
  MarketplaceItem,
  MarketplaceMeta,
  PoolSkillSpec,
  SkillSpec,
  SkillsMarketSpec,
} from "../../../api/types";
import {
  SkillCard,
  SkillDrawer,
  type SkillDrawerFormValues,
  useConflictRenameModal,
  ImportHubModal,
  MarketplaceDrawer,
  PoolTransferModal,
} from "./components";
import { useSkills } from "./useSkills";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import { parseErrorDetail } from "../../../utils/error";
import styles from "./index.module.less";

function SkillsPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const {
    skills,
    loading,
    uploading,
    importing,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    refreshSkills,
  } = useSkills();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillSpec | null>(null);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [form] = Form.useForm<SkillDrawerFormValues>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [poolModal, setPoolModal] = useState<"upload" | "download" | null>(
    null,
  );
  const [marketDrawerOpen, setMarketDrawerOpen] = useState(false);
  const [marketDrafts, setMarketDrafts] = useState<SkillsMarketSpec[]>([]);
  const [marketCacheTtl, setMarketCacheTtl] = useState(600);
  const [marketOverwriteDefault, setMarketOverwriteDefault] = useState(false);
  const [marketConfigLoaded, setMarketConfigLoaded] = useState(false);
  const [savingMarkets, setSavingMarkets] = useState(false);
  const [marketplace, setMarketplace] = useState<MarketplaceItem[]>([]);
  const [marketErrors, setMarketErrors] = useState<MarketError[]>([]);
  const [marketMeta, setMarketMeta] = useState<MarketplaceMeta | null>(null);
  const [marketplaceLoading, setMarketplaceLoading] = useState(false);
  const [installingSkillKey, setInstallingSkillKey] = useState<string | null>(
    null,
  );
  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  const MAX_UPLOAD_SIZE_MB = 100;

  const createEmptyMarketDraft = (): SkillsMarketSpec => ({
    id: "",
    name: "",
    url: "",
    branch: "",
    path: "index.json",
    enabled: true,
    order: marketDrafts.length,
    trust: null,
  });

  // Only fetch pool skills when pool modal is opened, not on page load
  useEffect(() => {
    if (poolModal === "upload" || poolModal === "download") {
      void api
        .listSkillPoolSkills()
        .then(setPoolSkills)
        .catch(() => undefined);
    }
  }, [poolModal]);

  const closePoolModal = () => {
    setPoolModal(null);
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    e.target.value = "";

    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }

    const sizeMB = file.size / (1024 * 1024);
    if (sizeMB > MAX_UPLOAD_SIZE_MB) {
      message.warning(
        t("skills.fileSizeExceeded", {
          limit: MAX_UPLOAD_SIZE_MB,
          size: sizeMB.toFixed(1),
        }),
      );
      return;
    }

    let renameMap: Record<string, string> | undefined;
    while (true) {
      const result = await uploadSkill(file, undefined, renameMap);
      if (result.success || !result.conflict) break;

      const conflicts = Array.isArray(result.conflict.conflicts)
        ? result.conflict.conflicts
        : [];
      if (conflicts.length === 0) break;

      const newRenames = await showConflictRenameModal(
        conflicts.map((c: { skill_name: string; suggested_name: string }) => ({
          key: c.skill_name,
          label: c.skill_name,
          suggested_name: c.suggested_name,
        })),
      );
      if (!newRenames) break;
      renameMap = { ...renameMap, ...newRenames };
    }
  };

  const handleCreate = () => {
    setEditingSkill(null);
    form.resetFields();
    form.setFieldsValue({
      enabled: false,
      channels: ["all"],
    });
    setDrawerOpen(true);
  };

  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
  };

  const loadMarketConfig = async () => {
    const payload = await api.getSkillMarkets();
    setMarketDrafts(payload.markets ?? []);
    setMarketCacheTtl(payload.cache?.ttl_sec ?? 600);
    setMarketOverwriteDefault(Boolean(payload.install?.overwrite_default));
    setMarketConfigLoaded(true);
  };

  const refreshMarketplace = async (refresh = true) => {
    setMarketplaceLoading(true);
    try {
      const res = await api.listMarketplace(refresh);
      setMarketplace(res.items ?? []);
      setMarketErrors(res.market_errors ?? []);
      setMarketMeta(res.meta ?? null);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("common.refresh"),
      );
    } finally {
      setMarketplaceLoading(false);
    }
  };

  const openMarketplaceDrawer = async () => {
    setMarketDrawerOpen(true);
    try {
      if (!marketConfigLoaded) {
        await loadMarketConfig();
      }
      await refreshMarketplace(false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("common.loading"));
    }
  };

  const handleAddMarket = () => {
    setMarketDrafts((prev) => [
      ...prev,
      {
        ...createEmptyMarketDraft(),
        order: prev.length,
      },
    ]);
  };

  const handleRemoveMarket = (idx: number) => {
    setMarketDrafts((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleUpdateMarket = (idx: number, patch: Partial<SkillsMarketSpec>) => {
    setMarketDrafts((prev) =>
      prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)),
    );
  };

  const handleValidateMarket = async (idx: number, draft?: SkillsMarketSpec) => {
    const row = draft ?? marketDrafts[idx];
    const validated = await api.validateSkillMarket({
      id: row.id,
      name: row.name,
      url: row.url,
      branch: row.branch,
      path: row.path,
      enabled: row.enabled,
      order: row.order,
    });
    setMarketDrafts((prev) =>
      prev.map((item, i) => (i === idx ? validated.normalized : item)),
    );
    if (validated.warnings?.length) {
      message.warning(validated.warnings.join("; "));
    } else {
      message.success(t("common.save"));
    }
  };

  const handleSaveMarkets = async () => {
    setSavingMarkets(true);
    try {
      const payload = await api.saveSkillMarkets({
        version: 1,
        cache: { ttl_sec: marketCacheTtl },
        install: { overwrite_default: marketOverwriteDefault },
        markets: marketDrafts,
      });
      setMarketDrafts(payload.markets ?? []);
      setMarketCacheTtl(payload.cache?.ttl_sec ?? 600);
      setMarketOverwriteDefault(Boolean(payload.install?.overwrite_default));
      message.success(t("common.save"));
      await refreshMarketplace(true);
    } finally {
      setSavingMarkets(false);
    }
  };

  const handleResetMarketTemplates = async () => {
    const payload = await api.resetSkillMarkets();
    setMarketDrafts(payload.markets ?? []);
    setMarketCacheTtl(payload.cache?.ttl_sec ?? 600);
    setMarketOverwriteDefault(Boolean(payload.install?.overwrite_default));
    message.success(t("common.reset"));
    await refreshMarketplace(true);
  };

  const handleInstallMarketSkill = async (marketId: string, skillId: string) => {
    const key = `${marketId}/${skillId}`;
    setInstallingSkillKey(key);
    try {
      await api.installMarketplaceSkill({
        market_id: marketId,
        skill_id: skillId,
        enable: true,
        overwrite: marketOverwriteDefault,
      });
      message.success(`${t("common.download")}: ${skillId}`);
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
      return true;
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.message) {
        message.error(detail.message);
      } else {
        message.error(error instanceof Error ? error.message : t("common.download"));
      }
      return false;
    } finally {
      setInstallingSkillKey(null);
    }
  };

  const handleRunBulkMarketAction = async (params: {
    type: "enable" | "disable" | "delete";
    marketId: string;
    shouldStop: () => boolean;
    onProgress?: (skillKey: string | null) => void;
  }) => {
    const targets = marketplace.filter((item) => item.market_id === params.marketId);

    if (params.type === "enable") {
      let enabled = 0;
      let installed = 0;
      let failed = 0;
      let stopped = false;
      for (const item of targets) {
        if (params.shouldStop()) {
          stopped = true;
          break;
        }
        params.onProgress?.(`${item.market_id}/${item.skill_id}`);
        try {
          const result = await api.installMarketplaceSkill({
            market_id: item.market_id,
            skill_id: item.skill_id,
            enable: true,
            overwrite: marketOverwriteDefault,
          });
          if (result.installed) installed += 1;
          if (result.enabled) enabled += 1;
        } catch {
          failed += 1;
        }
      }
      params.onProgress?.(null);
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
      return {
        type: "enable" as const,
        total: targets.length,
        affected: enabled + installed,
        failed,
        enabled,
        installed,
        stopped,
      };
    }

    if (params.type === "disable") {
      let disabled = 0;
      let failed = 0;
      let stopped = false;
      for (const item of targets) {
        if (params.shouldStop()) {
          stopped = true;
          break;
        }
        params.onProgress?.(`${item.market_id}/${item.skill_id}`);
        try {
          await api.disableSkill(item.skill_id);
          disabled += 1;
        } catch {
          failed += 1;
        }
      }
      params.onProgress?.(null);
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
      return {
        type: "disable" as const,
        total: targets.length,
        affected: disabled,
        failed,
        disabled,
        stopped,
      };
    }

    let deleted = 0;
    let failed = 0;
    let stopped = false;
    for (const item of targets) {
      if (params.shouldStop()) {
        stopped = true;
        break;
      }
      params.onProgress?.(`${item.market_id}/${item.skill_id}`);
      try {
        const result = await api.deleteSkill(item.skill_id);
        if (result.deleted) deleted += 1;
      } catch {
        failed += 1;
      }
    }
    params.onProgress?.(null);
    invalidateSkillCache({ agentId: selectedAgent });
    await refreshSkills();
    return {
      type: "delete" as const,
      total: targets.length,
      affected: deleted,
      failed,
      deleted,
      stopped,
    };
  };

  const handleConfirmImport = async (url: string, targetName?: string) => {
    const result = await importFromHub(url, targetName);
    if (result.success) {
      closeImportModal();
    } else if (result.conflict) {
      const detail = result.conflict;
      const suggested =
        detail?.suggested_name || detail?.conflicts?.[0]?.suggested_name;
      if (suggested) {
        const skillName =
          detail?.skill_name || detail?.conflicts?.[0]?.skill_name || "";
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: String(suggested),
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            await handleConfirmImport(url, newName);
          }
        }
      }
    }
  };

  const handleEdit = (skill: SkillSpec) => {
    setEditingSkill(skill);
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
      enabled: skill.enabled,
      channels: skill.channels,
    });
    setDrawerOpen(true);
  };

  const handleToggleEnabled = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    await toggleEnabled(skill);
    await refreshSkills();
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteSkill(skill);
    // No need to refresh again as deleteSkill already calls fetchSkills
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSkill(null);
  };

  const handleSubmit = async (values: SkillSpec) => {
    if (editingSkill) {
      const sourceName = editingSkill.name;
      const targetName = values.name;
      try {
        const result = await api.saveSkill({
          name: targetName,
          content: values.content,
          source_name: sourceName !== targetName ? sourceName : undefined,
          config: values.config,
        });
        await api.updateSkillChannels(result.name, values.channels || ["all"]);
        if (result.mode === "noop") {
          setDrawerOpen(false);
          await refreshSkills();
          return;
        }
        message.success(
          result.mode === "rename"
            ? `${t("common.save")}: ${result.name}`
            : t("common.save"),
        );
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after mutation
        await refreshSkills();
      } catch (error) {
        const detail = parseErrorDetail(error);
        if (detail?.suggested_name) {
          const renameMap = await showConflictRenameModal([
            {
              key: targetName,
              label: targetName,
              suggested_name: detail.suggested_name,
            },
          ]);
          if (renameMap) {
            const newName = Object.values(renameMap)[0];
            if (newName) {
              await handleSubmit({ ...values, name: newName });
            }
          }
        } else {
          message.error(
            error instanceof Error ? error.message : t("common.save"),
          );
        }
      }
    } else {
      const submitName = values.name;
      const result = await createSkill(
        submitName,
        values.content,
        values.config,
        true,
      );
      if (result.success) {
        await api.updateSkillChannels(submitName, values.channels || ["all"]);
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent }); // Clear cache after updating channels
        await refreshSkills();
        return;
      }
      if (result.conflict?.suggested_name) {
        const renameMap = await showConflictRenameModal([
          {
            key: submitName,
            label: submitName,
            suggested_name: result.conflict!.suggested_name,
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            await handleSubmit({ ...values, name: newName });
          }
        }
      }
    }
  };

  const handleUploadToPool = async (workspaceSkillNames: string[]) => {
    if (workspaceSkillNames.length === 0) return;
    try {
      for (const skillName of workspaceSkillNames) {
        let newName: string | undefined;
        while (true) {
          try {
            await api.uploadWorkspaceSkillToPool({
              workspace_id: selectedAgent,
              skill_name: skillName,
              new_name: newName,
            });
            break;
          } catch (error) {
            const detail = parseErrorDetail(error);
            if (!detail?.suggested_name) throw error;
            const renameMap = await showConflictRenameModal([
              {
                key: skillName,
                label: skillName,
                suggested_name: detail.suggested_name,
              },
            ]);
            if (!renameMap) return;
            newName = Object.values(renameMap)[0] || undefined;
          }
        }
      }
      message.success(t("skills.uploadedToPool"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true }); // Clear current agent and pool cache
      await refreshSkills();
      setPoolSkills(await api.listSkillPoolSkills());
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    }
  };

  const handleDownloadFromPool = async (poolSkillNames: string[]) => {
    if (poolSkillNames.length === 0) return;
    try {
      for (const skillName of poolSkillNames) {
        let targetName: string | undefined;
        while (true) {
          try {
            await api.downloadSkillPoolSkill({
              skill_name: skillName,
              targets: [
                {
                  workspace_id: selectedAgent,
                  target_name: targetName,
                },
              ],
            });
            break;
          } catch (error) {
            const detail = parseErrorDetail(error);
            const conflict = detail?.conflicts?.[0];
            if (!conflict?.suggested_name) throw error;
            const renameMap = await showConflictRenameModal([
              {
                key: skillName,
                label: skillName,
                suggested_name: conflict.suggested_name,
              },
            ]);
            if (!renameMap) return;
            targetName = Object.values(renameMap)[0] || undefined;
          }
        }
      }
      message.success(t("skills.downloadedToWorkspace"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true }); // Clear current agent and pool cache
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("common.download") + " failed",
      );
    }
  };

  return (
    <div className={styles.skillsPage}>
      <div className={styles.pageHeader}>
        <div className={styles.breadcrumbHeader}>
          <span className={styles.breadcrumbParent}>Agent</span>
          <span className={styles.breadcrumbSeparator}>/</span>
          <span className={styles.breadcrumbCurrent}>{t("skills.title")}</span>
        </div>
        <div className={styles.headerRight}>
          <input
            type="file"
            accept=".zip"
            ref={fileInputRef}
            onChange={handleFileChange}
            style={{ display: "none" }}
          />
          <div className={styles.headerActionsLeft}>
            <Tooltip title={t("skills.downloadFromPoolHint")}>
              <Button
                type="default"
                className={styles.primaryTransferButton}
                onClick={() => setPoolModal("download")}
                icon={<DownloadOutlined />}
              >
                {t("skills.downloadFromPool")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.uploadToPoolHint")}>
              <Button
                type="default"
                className={styles.primaryTransferButton}
                onClick={() => setPoolModal("upload")}
                icon={<SwapOutlined />}
              >
                {t("skills.uploadToPool")}
              </Button>
            </Tooltip>
          </div>
          <div className={styles.headerActionsRight}>
            <Tooltip title={t("skills.uploadZipHint")}>
              <Button
                type="default"
                className={styles.creationActionButton}
                onClick={handleUploadClick}
                icon={<UploadOutlined />}
                loading={uploading}
                disabled={uploading}
              >
                {t("skills.uploadZip")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.importHubHint")}>
              <Button
                type="default"
                className={styles.creationActionButton}
                onClick={() => setImportModalOpen(true)}
                icon={<ImportOutlined />}
              >
                {t("skills.importHub")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.marketplaceManageHint")}>
              <Button
                type="default"
                className={styles.creationActionButton}
                onClick={() => {
                  void openMarketplaceDrawer();
                }}
                icon={<AppstoreAddOutlined />}
              >
                {t("skills.marketplaceManage")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.createSkillHint")}>
              <Button
                type="primary"
                className={styles.primaryActionButton}
                onClick={handleCreate}
                icon={<PlusOutlined />}
              >
                {t("skills.createSkill")}
              </Button>
            </Tooltip>
          </div>
        </div>
      </div>

      <ImportHubModal
        open={importModalOpen}
        importing={importing}
        onCancel={closeImportModal}
        onConfirm={handleConfirmImport}
        cancelImport={cancelImport}
        hint="External hub import is separate from the local Skill Pool."
      />

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : skills.length === 0 ? (
        <div className={styles.emptyState}>
          <div className={styles.emptyStateBadge}>
            {t("skills.emptyStateBadge")}
          </div>
          <h2 className={styles.emptyStateTitle}>
            {t("skills.emptyStateTitle")}
          </h2>
          <p className={styles.emptyStateText}>{t("skills.emptyStateText")}</p>
          <div className={styles.emptyStateActions}>
            <Button
              type="default"
              className={styles.primaryTransferButton}
              onClick={() => setPoolModal("download")}
              icon={<DownloadOutlined />}
            >
              {t("skills.emptyStateDownload")}
            </Button>
            <Button
              type="primary"
              className={styles.primaryActionButton}
              onClick={handleCreate}
              icon={<PlusOutlined />}
            >
              {t("skills.emptyStateCreate")}
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.skillsGrid}>
          {skills
            .slice()
            .sort((a, b) => {
              if (a.enabled && !b.enabled) return -1;
              if (!a.enabled && b.enabled) return 1;
              return a.name.localeCompare(b.name);
            })
            .map((skill) => (
              <SkillCard
                key={skill.name}
                skill={skill}
                isHover={hoverKey === skill.name}
                onClick={() => handleEdit(skill)}
                onMouseEnter={() => setHoverKey(skill.name)}
                onMouseLeave={() => setHoverKey(null)}
                onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
                onDelete={(e) => handleDelete(skill, e)}
              />
            ))}
        </div>
      )}

      <PoolTransferModal
        mode={poolModal}
        skills={skills}
        poolSkills={poolSkills}
        onCancel={closePoolModal}
        onUpload={handleUploadToPool}
        onDownload={handleDownloadFromPool}
      />

      {conflictRenameModal}

      <SkillDrawer
        open={drawerOpen}
        editingSkill={editingSkill}
        form={form}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />

      <MarketplaceDrawer
        open={marketDrawerOpen}
        onClose={() => setMarketDrawerOpen(false)}
        marketDrafts={marketDrafts}
        marketCacheTtl={marketCacheTtl}
        marketOverwriteDefault={marketOverwriteDefault}
        savingMarkets={savingMarkets}
        onAddMarket={handleAddMarket}
        onRemoveMarket={handleRemoveMarket}
        onUpdateMarket={handleUpdateMarket}
        onValidateMarket={handleValidateMarket}
        onSaveMarkets={handleSaveMarkets}
        onResetMarketTemplates={() => {
          void handleResetMarketTemplates();
        }}
        onCacheTtlChange={setMarketCacheTtl}
        onOverwriteDefaultChange={setMarketOverwriteDefault}
        marketplace={marketplace}
        marketErrors={marketErrors}
        marketMeta={marketMeta}
        marketplaceLoading={marketplaceLoading}
        onRefreshMarketplace={() => {
          void refreshMarketplace(true);
        }}
        installingSkillKey={installingSkillKey}
        onInstallSkill={handleInstallMarketSkill}
        onRunBulkAction={handleRunBulkMarketAction}
      />
    </div>
  );
}

export default SkillsPage;
