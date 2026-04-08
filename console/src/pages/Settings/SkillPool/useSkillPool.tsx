import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Form, Modal } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type {
  BuiltinImportSpec,
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../api/types";
import { parseErrorDetail } from "../../../utils/error";
import { handleScanError, checkScanWarnings } from "../../../utils/scanError";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import {
  getSkillDisplaySource,
  parseFrontmatter,
  useConflictRenameModal,
} from "../../Agent/Skills/components";
import { useSkillFilter } from "../../Agent/Skills/useSkillFilter";

export type PoolMode = "broadcast" | "create" | "edit";

const SKILL_POOL_ZIP_MAX_MB = 100;

export function useSkillPool() {
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
  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();
  const { message } = useAppMessage();
  const [selectedPoolSkills, setSelectedPoolSkills] = useState<Set<string>>(
    new Set(),
  );
  const [batchModeEnabled, setBatchModeEnabled] = useState(false);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [filterOpen, setFilterOpen] = useState(false);
  const {
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allCategories,
    allTags,
    filteredSkills,
  } = useSkillFilter(skills);

  const sortedSkills = useMemo(
    () => filteredSkills.slice().sort((a, b) => a.name.localeCompare(b.name)),
    [filteredSkills],
  );

  const togglePoolSelect = (name: string) => {
    setSelectedPoolSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const clearPoolSelection = () => {
    setSelectedPoolSkills(new Set());
    setBatchModeEnabled(false);
  };

  const toggleBatchMode = () => {
    if (batchModeEnabled) {
      clearPoolSelection();
    } else {
      setBatchModeEnabled(true);
    }
  };

  const selectAllPool = () =>
    setSelectedPoolSkills(new Set(filteredSkills.map((s) => s.name)));

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

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      invalidateSkillCache({ pool: true, workspaces: true });
      const [poolSkills, workspaceSummaries] = await Promise.all([
        api.refreshSkillPool(),
        api.listSkillWorkspaces(),
      ]);
      setSkills(poolSkills);
      setWorkspaces(workspaceSummaries);
      dataLoadedRef.current = true;
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "Failed to refresh",
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
      tags: [],
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
      tags: skill.tags || [],
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

            // Separate builtin upgrades from regular conflicts.
            const builtinUpgrades = conflicts.filter(
              (c: { reason?: string }) => c.reason === "builtin_upgrade",
            );
            const regularConflicts = conflicts.filter(
              (c: { reason?: string }) => c.reason !== "builtin_upgrade",
            );

            // Handle builtin upgrades: confirm overwrite
            let needsOverwrite = false;
            if (builtinUpgrades.length > 0) {
              const confirmed = await new Promise<boolean>((resolve) => {
                Modal.confirm({
                  title: t("skills.builtinUpgradeTitle"),
                  content: t("skills.builtinUpgradeContent", {
                    name: skillName,
                  }),
                  okText: t("common.confirm"),
                  cancelText: t("common.cancel"),
                  onOk: () => resolve(true),
                  onCancel: () => resolve(false),
                });
              });
              if (!confirmed) return;
              needsOverwrite = true;
            }

            // Handle regular conflicts: rename modal
            if (regularConflicts.length > 0) {
              const renameItems = regularConflicts
                .map(
                  (c: { workspace_id?: string; suggested_name?: string }) => {
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
                  },
                )
                .filter(
                  (
                    item,
                  ): item is {
                    key: string;
                    label: string;
                    suggested_name: string;
                  } => item !== null,
                );

              if (!renameItems.length && !needsOverwrite) {
                throw error;
              }

              if (renameItems.length) {
                const nextRenameMap = await showConflictRenameModal(
                  renameItems.map((item) => ({
                    ...item,
                    suggested_name: renameMap[item.key] || item.suggested_name,
                  })),
                );
                if (!nextRenameMap) return;
                renameMap = { ...renameMap, ...nextRenameMap };
              }
            }

            // No conflicts left to resolve but nothing actionable
            if (!needsOverwrite && !regularConflicts.length) {
              throw error;
            }

            // Retry: overwrite is safe — renamed targets use new
            // names so won't be affected by the overwrite flag.
            if (needsOverwrite) {
              await api.downloadSkillPoolSkill({
                skill_name: skillName,
                targets: targetWorkspaceIds.map((workspace_id) => ({
                  workspace_id,
                  target_name: renameMap[workspace_id] || undefined,
                })),
                overwrite: true,
              });
              break;
            }
            // Only regular conflicts — renameMap already updated
            // above; loop continues to retry with new names.
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
      invalidateSkillCache({ pool: true });
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
              {conflicts.map(
                (item: {
                  skill_name: string;
                  current_version_text?: string;
                  source_version_text?: string;
                }) => (
                  <div key={item.skill_name}>
                    <strong>{item.skill_name}</strong>
                    {"  "}
                    {t("skillPool.currentVersion")}:{" "}
                    {item.current_version_text || "-"}
                    {"  ->  "}
                    {t("skillPool.sourceVersion")}:{" "}
                    {item.source_version_text || "-"}
                  </div>
                ),
              )}
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
      const newTags = values.tags || [];
      const oldTags = (mode === "edit" ? activeSkill?.tags : []) || [];
      const tagsChanged = JSON.stringify(newTags) !== JSON.stringify(oldTags);
      if (tagsChanged) {
        await api.updatePoolSkillTags(result.name || skillName, newTags);
      }
      if (result.mode === "noop" && !tagsChanged) {
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
        invalidateSkillCache({ pool: true });
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
        invalidateSkillCache({ pool: true });
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
      invalidateSkillCache({ pool: true });
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

  const handleBatchDeletePool = async () => {
    const names = Array.from(selectedPoolSkills);
    if (names.length === 0) return;
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("skillPool.batchDeleteTitle", { count: names.length }),
        content: (
          <ul style={{ margin: "8px 0", paddingLeft: 20 }}>
            {names.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ),
        okText: t("common.delete"),
        okType: "danger",
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!confirmed) return;
    try {
      const { results } = await api.batchDeletePoolSkills(names);
      const failed = Object.entries(results).filter(([, r]) => !r.success);
      if (failed.length > 0) {
        message.warning(
          t("skillPool.batchDeletePartial", {
            deleted: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skillPool.batchDeleteSuccess", { count: names.length }),
        );
      }
      clearPoolSelection();
      invalidateSkillCache({ pool: true });
      await loadData(true);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillPool.batchDeleteFailed"),
      );
    }
  };

  return {
    // Data
    skills,
    workspaces,
    loading,
    sortedSkills,
    // Mode / UI
    mode,
    activeSkill,
    viewMode,
    setViewMode,
    batchModeEnabled,
    filterOpen,
    setFilterOpen,
    // Search / Filter
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allCategories,
    allTags,
    // Selection
    selectedPoolSkills,
    togglePoolSelect,
    clearPoolSelection,
    toggleBatchMode,
    selectAllPool,
    // Modals
    importModalOpen,
    setImportModalOpen,
    importing,
    importBuiltinModalOpen,
    builtinSources,
    importBuiltinLoading,
    broadcastInitialNames,
    // Form / Drawer
    form,
    drawerContent,
    showMarkdown,
    setShowMarkdown,
    configText,
    setConfigText,
    // Refs
    zipInputRef,
    // Handlers
    handleRefresh,
    openCreate,
    openBroadcast,
    openImportBuiltin,
    closeImportBuiltin,
    closeImportModal,
    openEdit,
    closeDrawer,
    closeModal,
    handleDrawerContentChange,
    validateFrontmatter,
    handleSavePoolSkill,
    handleDelete,
    handleZipImport,
    handleConfirmImport,
    handleBroadcast,
    handleImportBuiltins,
    handleBatchDeletePool,
    // Conflict rename modal element
    conflictRenameModal,
  };
}
