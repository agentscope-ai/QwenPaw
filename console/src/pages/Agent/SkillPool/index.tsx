import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Input,
  Modal,
  Tooltip,
  message,
  Drawer,
  Form,
} from "@agentscope-ai/design";
import {
  AppstoreAddOutlined,
  ImportOutlined,
  PlusOutlined,
  SendOutlined,
  SyncOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type {
  BuiltinImportSpec,
  MarketError,
  MarketplaceItem,
  MarketplaceMeta,
  PoolSkillSpec,
  SkillsMarketSpec,
  WorkspaceSkillSummary,
} from "../../../api/types";
import { parseErrorDetail } from "../../../utils/error";
import { handleScanError, checkScanWarnings } from "../../../utils/scanError";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import {
  getSkillDisplaySource,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  getSkillVisual,
  parseFrontmatter,
  useConflictRenameModal,
  ImportHubModal,
  MarketplaceDrawer,
} from "../Skills/components";
import { MarkdownCopy } from "../../../components/MarkdownCopy/MarkdownCopy";
import { BroadcastModal } from "./components/BroadcastModal";
import { ImportBuiltinModal } from "./components/ImportBuiltinModal";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

type PoolMode = "broadcast" | "create" | "edit";

const SKILL_POOL_ZIP_MAX_MB = 100;

function SkillPoolPage() {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<PoolSkillSpec[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSkillSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<PoolMode | null>(null);
  const [activeSkill, setActiveSkill] = useState<PoolSkillSpec | null>(null);
  const [broadcastInitialNames, setBroadcastInitialNames] = useState<string[]>(
    [],
  );
  const [configText, setConfigText] = useState("{}");
  const zipInputRef = useRef<HTMLInputElement>(null);
  const [importBuiltinModalOpen, setImportBuiltinModalOpen] = useState(false);
  const [builtinSources, setBuiltinSources] = useState<BuiltinImportSpec[]>([]);
  const [importBuiltinLoading, setImportBuiltinLoading] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [marketDrawerOpen, setMarketDrawerOpen] = useState(false);
  const [marketDrafts, setMarketDrafts] = useState<SkillsMarketSpec[]>([]);
  const [marketCacheTtl, setMarketCacheTtl] = useState(600);
  const [marketOverwriteDefault, setMarketOverwriteDefault] = useState(false);
  const [marketConfigLoaded, setMarketConfigLoaded] = useState(false);
  const [savingMarkets, setSavingMarkets] = useState(false);
  const [marketErrors, setMarketErrors] = useState<MarketError[]>([]);
  const [marketMeta, setMarketMeta] = useState<MarketplaceMeta | null>(null);
  const [marketplaceLoading, setMarketplaceLoading] = useState(false);
  const [marketplace, setMarketplace] = useState<MarketplaceItem[]>([]);
  const [installingSkillKey, setInstallingSkillKey] = useState<string | null>(
    null,
  );
  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  // Form state for create/edit drawer
  const [form] = Form.useForm();
  const [drawerContent, setDrawerContent] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(true);

  // Use ref to cache data and avoid unnecessary reloads
  const dataLoadedRef = useRef(false);

  const loadData = useCallback(async (forceReload = false) => {
    // Skip if already loaded and not forcing reload
    if (dataLoadedRef.current && !forceReload) return;

    setLoading(true);
    try {
      const [poolSkills, workspaceSummaries] = await Promise.all([
        api.listSkillPoolSkills(),
        api.listSkillWorkspaces(),
      ]);
      setSkills(poolSkills);
      setWorkspaces(workspaceSummaries);
      dataLoadedRef.current = true;
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "Failed to load skill pool",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const closeModal = () => {
    setMode(null);
    setBroadcastInitialNames([]);
    setConfigText("{}");
  };

  const openCreate = () => {
    setMode("create");
    setDrawerContent("");
    setConfigText("{}");
    form.resetFields();
    form.setFieldsValue({
      name: "",
      content: "",
    });
  };

  const openBroadcast = (skill?: PoolSkillSpec) => {
    setMode("broadcast");
    setBroadcastInitialNames(skill ? [skill.name] : []);
  };

  const openImportBuiltin = async () => {
    try {
      setImportBuiltinLoading(true);
      const sources = await api.listPoolBuiltinSources();
      setBuiltinSources(sources);
      setImportBuiltinModalOpen(true);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillPool.importBuiltinFailed"),
      );
    } finally {
      setImportBuiltinLoading(false);
    }
  };

  const loadMarketConfig = async () => {
    const payload = await api.getSkillMarkets();
    setMarketDrafts(payload.markets ?? []);
    setMarketCacheTtl(payload.cache?.ttl_sec ?? 600);
    setMarketOverwriteDefault(Boolean(payload.install?.overwrite_default));
    setMarketConfigLoaded(true);
  };

  const refreshMarketplace = useCallback(async (refresh = true) => {
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
  }, [t]);

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

  const closeImportBuiltin = () => {
    if (importBuiltinLoading) return;
    setImportBuiltinModalOpen(false);
  };

  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
  };

  const openEdit = (skill: PoolSkillSpec) => {
    setMode("edit");
    setActiveSkill(skill);
    setDrawerContent(skill.content);
    setConfigText(JSON.stringify(skill.config || {}, null, 2));
    form.setFieldsValue({
      name: skill.name,
      content: skill.content,
    });
  };

  const closeDrawer = () => {
    setMode(null);
    setActiveSkill(null);
  };

  const handleDrawerContentChange = (content: string) => {
    setDrawerContent(content);
    form.setFieldsValue({ content });
  };

  const validateFrontmatter = useCallback(
    (_: unknown, value: string) => {
      const content = drawerContent || value;
      if (!content || !content.trim()) {
        return Promise.reject(new Error(t("skills.pleaseInputContent")));
      }
      const fm = parseFrontmatter(content);
      if (!fm) {
        return Promise.reject(new Error(t("skills.frontmatterRequired")));
      }
      if (!fm.name) {
        return Promise.reject(new Error(t("skills.frontmatterNameRequired")));
      }
      if (!fm.description) {
        return Promise.reject(
          new Error(t("skills.frontmatterDescriptionRequired")),
        );
      }
      return Promise.resolve();
    },
    [drawerContent, t],
  );

  const handleBroadcast = async (
    broadcastSkillNames: string[],
    targetWorkspaceIds: string[],
  ) => {
    try {
      for (const skillName of broadcastSkillNames) {
        let renameMap: Record<string, string> = {};

        while (true) {
          try {
            await api.downloadSkillPoolSkill({
              skill_name: skillName,
              targets: targetWorkspaceIds.map((workspace_id) => ({
                workspace_id,
                target_name: renameMap[workspace_id] || undefined,
              })),
            });
            break;
          } catch (error) {
            if (handleScanError(error, t)) return;
            const detail = parseErrorDetail(error);
            const conflicts = Array.isArray(detail?.conflicts)
              ? detail.conflicts
              : [];
            if (!conflicts.length) {
              throw error;
            }

            const renameItems = conflicts
              .map((c: { workspace_id?: string; suggested_name?: string }) => {
                if (!c.workspace_id || !c.suggested_name) {
                  return null;
                }
                const w = workspaces.find(
                  (ws) => ws.agent_id === c.workspace_id,
                );
                const workspaceLabel = getAgentDisplayName(
                  {
                    id: c.workspace_id,
                    name: w?.agent_name ?? "",
                  },
                  t,
                );
                return {
                  key: c.workspace_id,
                  label: workspaceLabel,
                  suggested_name: c.suggested_name,
                };
              })
              .filter(
                (
                  item,
                ): item is {
                  key: string;
                  label: string;
                  suggested_name: string;
                } => item !== null,
              );

            if (!renameItems.length) {
              throw error;
            }

            const nextRenameMap = await showConflictRenameModal(
              renameItems.map((item) => ({
                ...item,
                suggested_name: renameMap[item.key] || item.suggested_name,
              })),
            );
            if (!nextRenameMap) {
              return;
            }
            renameMap = {
              ...renameMap,
              ...nextRenameMap,
            };
          }
        }
      }
      message.success(t("skillPool.broadcastSuccess"));
      closeModal();
      invalidateSkillCache({ pool: true, workspaces: true });
      await loadData(true);
      for (const skillName of broadcastSkillNames) {
        await checkScanWarnings(
          skillName,
          api.getBlockedHistory,
          api.getSkillScanner,
          t,
        );
      }
    } catch (error) {
      if (!handleScanError(error, t)) {
        message.error(
          error instanceof Error
            ? error.message
            : t("skillPool.broadcastFailed"),
        );
      }
    }
  };

  const handleImportBuiltins = async (
    selectedNames: string[],
    overwriteConflicts: boolean = false,
  ) => {
    if (selectedNames.length === 0) return;
    try {
      setImportBuiltinLoading(true);
      const result = await api.importSelectedPoolBuiltins({
        skill_names: selectedNames,
        overwrite_conflicts: overwriteConflicts,
      });
      const imported = Array.isArray(result.imported) ? result.imported : [];
      const updated = Array.isArray(result.updated) ? result.updated : [];
      const unchanged = Array.isArray(result.unchanged) ? result.unchanged : [];

      if (!imported.length && !updated.length && unchanged.length) {
        message.info(t("skillPool.importBuiltinNoChanges"));
        closeImportBuiltin();
        return;
      }

      if (imported.length || updated.length) {
        message.success(
          t("skillPool.importBuiltinSuccess", {
            names: [...imported, ...updated].join(", "),
          }),
        );
      }
      closeImportBuiltin();
      invalidateSkillCache({ pool: true }); // Clear pool cache
      await loadData(true);
    } catch (error) {
      const detail = parseErrorDetail(error);
      const conflicts = Array.isArray(detail?.conflicts)
        ? detail.conflicts
        : [];
      if (conflicts.length && !overwriteConflicts) {
        Modal.confirm({
          title: t("skillPool.importBuiltinConflictTitle"),
          content: (
            <div style={{ display: "grid", gap: 8 }}>
              <div>{t("skillPool.importBuiltinConflictContent")}</div>
              {conflicts.map((item) => (
                <div key={item.skill_name}>
                  <strong>{item.skill_name}</strong>
                  {"  "}
                  {t("skillPool.currentVersion")}:{" "}
                  {item.current_version_text || "-"}
                  {"  ->  "}
                  {t("skillPool.sourceVersion")}:{" "}
                  {item.source_version_text || "-"}
                </div>
              ))}
            </div>
          ),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            await handleImportBuiltins(selectedNames, true);
          },
        });
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("skillPool.importBuiltinFailed"),
      );
    } finally {
      setImportBuiltinLoading(false);
    }
  };

  const handleSavePoolSkill = async () => {
    const values = await form.validateFields().catch(() => null);
    if (!values) return;

    const trimmedConfig = configText.trim();
    let parsedConfig: Record<string, unknown> = {};
    if (trimmedConfig && trimmedConfig !== "{}") {
      try {
        parsedConfig = JSON.parse(trimmedConfig);
      } catch {
        message.error(t("skills.configInvalidJson"));
        return;
      }
    }

    const skillName = (values.name || "").trim();
    const skillContent = drawerContent || values.content;

    if (!skillName || !skillContent.trim()) return;

    try {
      const result =
        mode === "edit"
          ? await api.saveSkillPoolSkill({
              name: skillName,
              content: skillContent,
              source_name: activeSkill?.name,
              config: parsedConfig,
            })
          : await api
              .createSkillPoolSkill({
                name: skillName,
                content: skillContent,
                config: parsedConfig,
              })
              .then((created) => ({
                success: true,
                mode: "edit" as const,
                name: created.name,
              }));
      if (result.mode === "noop") {
        closeDrawer();
        return;
      }
      const savedAsNew =
        mode === "edit" && activeSkill && result.name !== activeSkill.name;
      message.success(
        savedAsNew
          ? `${t("common.create")}: ${result.name}`
          : mode === "edit"
          ? t("common.save")
          : t("common.create"),
      );
      closeDrawer();
      invalidateSkillCache({ pool: true });
      await loadData(true);
      await checkScanWarnings(
        result.name || skillName,
        api.getBlockedHistory,
        api.getSkillScanner,
        t,
      );
    } catch (error) {
      if (handleScanError(error, t)) return;
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: detail.suggested_name,
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            form.setFieldsValue({ name: newName });
            await handleSavePoolSkill();
          }
        }
        return;
      }
      message.error(
        error instanceof Error ? error.message : t("common.save") + " failed",
      );
    }
  };

  const handleDelete = async (skill: PoolSkillSpec) => {
    Modal.confirm({
      title: t("skillPool.deleteTitle", { name: skill.name }),
      content:
        getSkillDisplaySource(skill.source) === "builtin"
          ? t("skillPool.deleteBuiltinConfirm")
          : t("skillPool.deleteConfirm"),
      okText: t("common.delete"),
      okType: "danger",
      onOk: async () => {
        await api.deleteSkillPoolSkill(skill.name);
        message.success(t("skillPool.deletedFromPool"));
        invalidateSkillCache({ pool: true }); // Clear pool cache
        await loadData(true);
      },
    });
  };

  const handleZipImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }

    const sizeMB = file.size / (1024 * 1024);
    if (sizeMB > SKILL_POOL_ZIP_MAX_MB) {
      message.warning(
        t("skills.fileSizeExceeded", {
          limit: SKILL_POOL_ZIP_MAX_MB,
          size: sizeMB.toFixed(1),
        }),
      );
      return;
    }

    let renameMap: Record<string, string> | undefined;
    while (true) {
      try {
        const result = await api.uploadSkillPoolZip(file, {
          overwrite: false,
          rename_map: renameMap,
        });
        if (result.count > 0) {
          message.success(
            t("skillPool.imported", { names: result.imported.join(", ") }),
          );
        } else {
          message.info(t("skillPool.noNewImports"));
        }
        invalidateSkillCache({ pool: true }); // Clear pool cache
        await loadData(true);
        if (result.count > 0 && Array.isArray(result.imported)) {
          for (const name of result.imported) {
            await checkScanWarnings(
              name,
              api.getBlockedHistory,
              api.getSkillScanner,
              t,
            );
          }
        }
        break;
      } catch (error) {
        const detail = parseErrorDetail(error);
        const conflicts = Array.isArray(detail?.conflicts)
          ? detail.conflicts
          : [];
        if (conflicts.length === 0) {
          if (handleScanError(error, t)) break;
          message.error(
            error instanceof Error
              ? error.message
              : t("skillPool.zipImportFailed"),
          );
          break;
        }
        const newRenames = await showConflictRenameModal(
          conflicts.map(
            (c: { skill_name?: string; suggested_name?: string }) => ({
              key: c.skill_name || "",
              label: c.skill_name || "",
              suggested_name: c.suggested_name || "",
            }),
          ),
        );
        if (!newRenames) break;
        renameMap = { ...renameMap, ...newRenames };
      }
    }
  };

  const handleConfirmImport = async (url: string, targetName?: string) => {
    try {
      setImporting(true);
      const result = await api.importPoolSkillFromHub({
        bundle_url: url,
        overwrite: false,
        target_name: targetName,
      });
      message.success(`${t("common.create")}: ${result.name}`);
      closeImportModal();
      invalidateSkillCache({ pool: true }); // Clear pool cache
      await loadData(true);
      await checkScanWarnings(
        result.name,
        api.getBlockedHistory,
        api.getSkillScanner,
        t,
      );
    } catch (error) {
      if (handleScanError(error, t)) return;
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        const skillName = detail?.skill_name || "";
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: String(detail.suggested_name),
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            await handleConfirmImport(url, newName);
          }
        }
        return;
      }
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    } finally {
      setImporting(false);
    }
  };

  const importMarketplaceSkillToPool = async (
    item: MarketplaceItem,
    targetName?: string,
  ): Promise<string | null> => {
    try {
      const result = await api.importPoolSkillFromHub({
        bundle_url: item.install_url,
        overwrite: false,
        target_name: targetName,
      });
      return result.name;
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        const skillName = detail?.skill_name || item.skill_id || "";
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: String(detail.suggested_name),
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            return importMarketplaceSkillToPool(item, newName);
          }
        }
        return null;
      }
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
      return null;
    }
  };

  const handleImportFromMarketplace = async (item: MarketplaceItem) => {
    const key = `${item.market_id}/${item.skill_id}`;
    try {
      setInstallingSkillKey(key);
      const importedName = await importMarketplaceSkillToPool(item);
      if (!importedName) return;

      message.success(`${t("common.create")}: ${importedName}`);
      invalidateSkillCache({ pool: true, workspaces: true });
      await loadData(true);
      setMarketDrawerOpen(false);
      setMode("broadcast");
      setBroadcastInitialNames([importedName]);
    } finally {
      setInstallingSkillKey(null);
    }
  };

  const handleInstallMarketSkill = async (marketId: string, skillId: string) => {
    const item = marketplace.find(
      (entry) => entry.market_id === marketId && entry.skill_id === skillId,
    );
    if (!item) {
      message.error(t("common.download"));
      return false;
    }
    await handleImportFromMarketplace(item);
    return true;
  };

  const resolvePoolSkillNameFromMarketItem = (item: MarketplaceItem) => {
    const bySource = skills.find((s) => s.source === item.source_url)?.name;
    if (bySource) return bySource;
    return skills.find((s) => s.name === item.skill_id)?.name || null;
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
      const broadcastSkillNames: string[] = [];
      for (const item of targets) {
        if (params.shouldStop()) {
          stopped = true;
          break;
        }
        params.onProgress?.(`${item.market_id}/${item.skill_id}`);
        const imported = await importMarketplaceSkillToPool(item);
        if (imported) {
          installed += 1;
          enabled += 1;
          broadcastSkillNames.push(imported);
        } else {
          failed += 1;
        }
      }
      params.onProgress?.(null);
      invalidateSkillCache({ pool: true });
      await loadData(true);
      if (broadcastSkillNames.length > 0) {
        const deduped = Array.from(new Set(broadcastSkillNames));
        setMarketDrawerOpen(false);
        setMode("broadcast");
        setBroadcastInitialNames(deduped);
      }
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
        const poolSkillName = resolvePoolSkillNameFromMarketItem(item);
        if (!poolSkillName) {
          failed += 1;
          continue;
        }
        try {
          await api.deleteSkillPoolSkill(poolSkillName);
          disabled += 1;
        } catch {
          failed += 1;
        }
      }
      params.onProgress?.(null);
      invalidateSkillCache({ pool: true });
      await loadData(true);
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
      const poolSkillName = resolvePoolSkillNameFromMarketItem(item);
      if (!poolSkillName) {
        failed += 1;
        continue;
      }
      try {
        const result = await api.deleteSkillPoolSkill(poolSkillName);
        if (result.deleted) deleted += 1;
      } catch {
        failed += 1;
      }
    }
    params.onProgress?.(null);
    invalidateSkillCache({ pool: true });
    await loadData(true);
    return {
      type: "delete" as const,
      total: targets.length,
      affected: deleted,
      failed,
      deleted,
      stopped,
    };
  };

  return (
    <div className={styles.skillsPage}>
      <PageHeader
        items={[{ title: t("nav.settings") }, { title: t("nav.skillPool") }]}
        extra={
          <div className={styles.headerRight}>
            <input
              type="file"
              accept=".zip"
              ref={zipInputRef}
              onChange={handleZipImport}
              style={{ display: "none" }}
            />
            <div className={styles.headerActionsLeft}>
              <Tooltip title={t("skillPool.broadcastHint")}>
                <Button
                  type="default"
                  className={styles.primaryTransferButton}
                  icon={<SendOutlined />}
                  onClick={() => openBroadcast()}
                >
                  {t("skillPool.broadcast")}
                </Button>
              </Tooltip>
              <Tooltip title={t("skillPool.importBuiltinHint")}>
                <Button
                  type="default"
                  icon={<SyncOutlined />}
                  onClick={() => void openImportBuiltin()}
                >
                  {t("skillPool.importBuiltin")}
                </Button>
              </Tooltip>
            </div>
            <div className={styles.headerActionsRight}>
              <Tooltip title={t("skillPool.uploadZipHint")}>
                <Button
                  type="default"
                  icon={<UploadOutlined />}
                  onClick={() => zipInputRef.current?.click()}
                >
                  {t("skills.uploadZip")}
                </Button>
              </Tooltip>
              <Tooltip title={t("skillPool.importHubHint")}>
                <Button
                  type="default"
                  icon={<ImportOutlined />}
                  onClick={() => setImportModalOpen(true)}
                >
                  {t("skills.importHub")}
                </Button>
              </Tooltip>
              <Tooltip title={t("skills.marketplaceManageHint")}>
                <Button
                  type="default"
                  icon={<AppstoreAddOutlined />}
                  onClick={() => void openMarketplaceDrawer()}
                >
                  {t("skills.marketplaceManage")}
                </Button>
              </Tooltip>
              <Tooltip title={t("skills.createSkillHint")}>
                <Button
                  type="primary"
                  className={styles.primaryActionButton}
                  icon={<PlusOutlined />}
                  onClick={openCreate}
                >
                  {t("skills.createSkill")}
                </Button>
              </Tooltip>
            </div>
          </div>
        }
      />

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : (
        <div className={styles.skillsGrid}>
          {skills.map((skill) => (
            <Card
              key={skill.name}
              className={styles.skillCard}
              onClick={() => openEdit(skill)}
              style={{ cursor: "pointer" }}
            >
              <div className={styles.cardBody}>
                <div className={styles.cardHeader}>
                  <div className={styles.leftSection}>
                    <span className={styles.fileIcon}>
                      {getSkillVisual(skill.name, skill.content)}
                    </span>
                    <div className={styles.titleRow}>
                      <h3 className={styles.skillTitle}>{skill.name}</h3>
                      <span
                        className={
                          getSkillDisplaySource(skill.source) === "builtin"
                            ? styles.builtinTag
                            : styles.customizedTag
                        }
                      >
                        {getSkillDisplaySource(skill.source) === "builtin"
                          ? t("skillPool.builtin")
                          : t("skillPool.custom")}
                      </span>
                    </div>
                    <div className={styles.statusRow}>
                      <span className={styles.statusLabel}>
                        {t("skillPool.status")}:
                      </span>
                      <span
                        className={`${styles.statusValue} ${
                          styles[getPoolBuiltinStatusTone(skill.sync_status)]
                        }`}
                      >
                        {getPoolBuiltinStatusLabel(skill.sync_status, t)}
                      </span>
                    </div>
                  </div>
                </div>
                <div className={styles.descriptionContainer}>
                  <p className={styles.descriptionLabel}>
                    {t("skillPool.descriptionLabel")}
                  </p>
                  <p className={styles.descriptionText}>
                    {skill.description || "-"}
                  </p>
                </div>
              </div>
              <div className={styles.cardFooter}>
                <Button
                  className={styles.actionButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    openBroadcast(skill);
                  }}
                >
                  {t("skillPool.broadcast")}
                </Button>
                <Button
                  className={styles.deleteButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleDelete(skill);
                  }}
                >
                  {t("skillPool.delete")}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <ImportHubModal
        open={importModalOpen}
        importing={importing}
        onCancel={closeImportModal}
        onConfirm={handleConfirmImport}
        hint={t("skillPool.externalHubHint")}
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
        installActionLabel={t("skillPool.broadcast")}
        enableAllActionLabel={t("skillPool.broadcastAll")}
        enableAllConfirmText={t("skillPool.broadcastAllConfirm")}
        bulkEnableLoadingText={t("skillPool.broadcastAllLoading")}
        enableAllSummaryActionLabel={t("skillPool.broadcastAll")}
        installAllInGroupLabel={t("skillPool.broadcastAllInGroup")}
        installAllInGroupStopLabel={t("skillPool.broadcastAllInGroupStop")}
        useBulkEnableForGroupInstall={true}
      />

      <BroadcastModal
        open={mode === "broadcast"}
        skills={skills}
        workspaces={workspaces}
        initialSkillNames={broadcastInitialNames}
        onCancel={closeModal}
        onConfirm={handleBroadcast}
      />

      <ImportBuiltinModal
        open={importBuiltinModalOpen}
        loading={importBuiltinLoading}
        sources={builtinSources}
        onCancel={closeImportBuiltin}
        onConfirm={handleImportBuiltins}
      />

      <Drawer
        width={520}
        placement="right"
        title={
          mode === "edit"
            ? t("skillPool.editTitle", { name: activeSkill?.name || "" })
            : t("skillPool.createTitle")
        }
        open={mode === "create" || mode === "edit"}
        onClose={closeDrawer}
        destroyOnClose
        footer={
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={closeDrawer}>{t("common.cancel")}</Button>
            <Button type="primary" onClick={handleSavePoolSkill}>
              {mode === "edit" ? t("common.save") : t("common.create")}
            </Button>
          </div>
        }
      >
        {mode === "edit" && activeSkill && (
          <div className={styles.metaStack} style={{ marginBottom: 16 }}>
            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>{t("skillPool.status")}</div>
              <div
                className={`${styles.infoBlock} ${
                  styles[getPoolBuiltinStatusTone(activeSkill.sync_status)]
                }`}
              >
                {getPoolBuiltinStatusLabel(activeSkill.sync_status, t)}
              </div>
            </div>
          </div>
        )}
        <Form form={form} layout="vertical" onFinish={handleSavePoolSkill}>
          <Form.Item
            name="name"
            label={t("skillPool.skillName")}
            rules={[{ required: true, message: t("skills.pleaseInputName") }]}
          >
            <Input placeholder={t("skillPool.skillNamePlaceholder")} />
          </Form.Item>

          <Form.Item
            name="content"
            label="Content"
            rules={[{ required: true, validator: validateFrontmatter }]}
          >
            <MarkdownCopy
              content={drawerContent}
              showMarkdown={showMarkdown}
              onShowMarkdownChange={setShowMarkdown}
              editable={true}
              onContentChange={handleDrawerContentChange}
              textareaProps={{
                placeholder: t("skillPool.contentPlaceholder"),
                rows: 12,
              }}
            />
          </Form.Item>

          <Form.Item label={t("skills.config")}>
            <Input.TextArea
              rows={4}
              value={configText}
              onChange={(e) => {
                setConfigText(e.target.value);
              }}
              placeholder={t("skills.configPlaceholder")}
            />
          </Form.Item>
        </Form>
      </Drawer>

      {conflictRenameModal}
    </div>
  );
}

export default SkillPoolPage;
