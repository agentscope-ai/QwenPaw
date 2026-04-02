import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@agentscope-ai/design";
import api from "../../../../api";
import { invalidateSkillCache } from "../../../../api/modules/skill";
import type {
  BuiltinImportSpec,
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { parseErrorDetail } from "../../../../utils/error";
import {
  handleScanError,
  checkScanWarnings,
} from "../../../../utils/scanError";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import {
  getSkillDisplaySource,
  parseFrontmatter,
  useConflictRenameModal,
} from "../../Skills/components";

const SKILL_POOL_ZIP_MAX_MB = 100;

export type PoolMode = "broadcast" | "create" | "edit";

export function useSkillPool() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  // ---- Core State ----
  const [skills, setSkills] = useState<PoolSkillSpec[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSkillSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<PoolMode | null>(null);
  const [activeSkill, setActiveSkill] = useState<PoolSkillSpec | null>(null);

  // ---- Batch Selection ----
  const [selectedPoolSkills, setSelectedPoolSkills] = useState<Set<string>>(
    new Set(),
  );
  const [batchModeEnabled, setBatchModeEnabled] = useState(false);
  const poolBatchMode = batchModeEnabled;

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
  };

  const toggleBatchMode = () => {
    if (batchModeEnabled) {
      clearPoolSelection();
      setBatchModeEnabled(false);
    } else {
      setBatchModeEnabled(true);
    }
  };

  const selectAllPool = () =>
    setSelectedPoolSkills(new Set(skills.map((s) => s.name)));

  // ---- Broadcast Modal ----
  const [broadcastInitialNames, setBroadcastInitialNames] = useState<string[]>(
    [],
  );

  // ---- Import Builtin Modal ----
  const [importBuiltinModalOpen, setImportBuiltinModalOpen] = useState(false);
  const [builtinSources, setBuiltinSources] = useState<BuiltinImportSpec[]>([]);
  const [importBuiltinLoading, setImportBuiltinLoading] = useState(false);

  // ---- Import Hub Modal ----
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importing, setImporting] = useState(false);

  // ---- Data Loading ----
  const dataLoadedRef = useRef(false);

  const loadData = useCallback(async (forceReload = false) => {
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

  // ---- Modal Controls ----
  const closeModal = () => {
    setMode(null);
    setBroadcastInitialNames([]);
  };

  const openBroadcast = (skill?: PoolSkillSpec) => {
    setMode("broadcast");
    setBroadcastInitialNames(skill ? [skill.name] : []);
  };

  const openCreate = () => {
    setMode("create");
    setActiveSkill(null);
  };

  const openEdit = (skill: PoolSkillSpec) => {
    setMode("edit");
    setActiveSkill(skill);
  };

  const closeDrawer = () => {
    setMode(null);
    setActiveSkill(null);
  };

  // ---- Import Builtin ----
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

  // ---- Import Hub ----
  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
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

  // ---- Broadcast ----
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

            const builtinUpgrades = conflicts.filter(
              (c: { reason?: string }) => c.reason === "builtin_upgrade",
            );
            const regularConflicts = conflicts.filter(
              (c: { reason?: string }) => c.reason !== "builtin_upgrade",
            );

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

            if (!needsOverwrite && !regularConflicts.length) {
              throw error;
            }

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

  // ---- Delete ----
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

  // ---- Batch Operations ----
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

  const handleBatchBroadcast = () => {
    const names = Array.from(selectedPoolSkills);
    if (names.length === 0) return;
    clearPoolSelection();
    setMode("broadcast");
    setBroadcastInitialNames(names);
  };

  // ---- Zip Import ----
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

  // ---- Save Skill ----
  const handleSavePoolSkill = async (
    formValues: { name: string; content: string },
    drawerContent: string,
    configText: string,
    setFormFieldsValue: (v: { name: string }) => void,
  ) => {
    const trimmedConfig = configText.trim();
    let parsedConfig: Record<string, unknown> = {};
    if (trimmedConfig && trimmedConfig !== "{}") {
      try {
        parsedConfig = JSON.parse(trimmedConfig);
      } catch {
        message.error(t("skills.configInvalidJson"));
        return false;
      }
    }

    const skillName = (formValues.name || "").trim();
    const skillContent = drawerContent || formValues.content;

    if (!skillName || !skillContent.trim()) return false;

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
        return true;
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
      return true;
    } catch (error) {
      if (handleScanError(error, t)) return false;
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
            setFormFieldsValue({ name: newName });
            return await handleSavePoolSkill(
              { ...formValues, name: newName },
              drawerContent,
              configText,
              setFormFieldsValue,
            );
          }
        }
        return false;
      }
      message.error(
        error instanceof Error ? error.message : t("common.save") + " failed",
      );
      return false;
    }
  };

  // ---- Validation ----
  const validateFrontmatter = (drawerContent: string, value: string) => {
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
  };

  return {
    // State
    skills,
    workspaces,
    loading,
    mode,
    activeSkill,
    selectedPoolSkills,
    poolBatchMode,
    batchModeEnabled,
    broadcastInitialNames,
    importBuiltinModalOpen,
    builtinSources,
    importBuiltinLoading,
    importModalOpen,
    importing,
    conflictRenameModal,

    // Selection Actions
    togglePoolSelect,
    clearPoolSelection,
    toggleBatchMode,
    selectAllPool,

    // Data Actions
    loadData,
    handleRefresh,

    // Modal Actions
    closeModal,
    openBroadcast,
    openCreate,
    openEdit,
    closeDrawer,
    openImportBuiltin,
    closeImportBuiltin,
    closeImportModal,
    setImportModalOpen,

    // Business Actions
    handleBroadcast,
    handleImportBuiltins,
    handleConfirmImport,
    handleDelete,
    handleBatchDeletePool,
    handleBatchBroadcast,
    handleZipImport,
    handleSavePoolSkill,
    validateFrontmatter,
  };
}
