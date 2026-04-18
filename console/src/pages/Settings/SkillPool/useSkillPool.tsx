import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Modal, Form } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type {
  BuiltinImportSpec,
  BuiltinUpdateNotice,
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../api/types";
import { parseErrorDetail } from "../../../utils/error";
import { handleScanError, checkScanWarnings } from "../../../utils/scanError";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import {
  parseFrontmatter,
  useConflictRenameModal,
} from "../../Agent/Skills/components";
import { useSkillFilter } from "../../Agent/Skills/useSkillFilter";

export type PoolMode = "broadcast" | "create" | "edit";

const SKILL_POOL_ZIP_MAX_MB = 100;
type BuiltinSkillLanguage = "en" | "zh";
interface BuiltinImportSelection {
  skill_name: string;
  language: BuiltinSkillLanguage;
}

type BroadcastConflict =
  | {
      skill_name: string;
      workspace_id: string;
      workspace_name: string;
      reason: "conflict";
    }
  | {
      skill_name: string;
      workspace_id: string;
      workspace_name: string;
      reason: "builtin_upgrade";
      current_version_text: string;
      source_version_text: string;
    };

const BUILTIN_NOTICE_ACK_STORAGE_KEY = "qwenpaw.skill-pool.builtin-notice.ack";

function readBuiltinNoticeAcknowledgement(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(BUILTIN_NOTICE_ACK_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeBuiltinNoticeAcknowledgement(fingerprint: string): void {
  if (typeof window === "undefined" || !fingerprint) return;
  try {
    localStorage.setItem(BUILTIN_NOTICE_ACK_STORAGE_KEY, fingerprint);
  } catch {
    // Ignore storage failures and fall back to in-memory state.
  }
}

export function useSkillPool() {
  const { t, i18n } = useTranslation();
  const [skills, setSkills] = useState<PoolSkillSpec[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSkillSummary[]>([]);
  const [builtinNotice, setBuiltinNotice] =
    useState<BuiltinUpdateNotice | null>(null);
  const [builtinNoticeAck, setBuiltinNoticeAck] = useState<string>(() =>
    readBuiltinNoticeAcknowledgement(),
  );
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
    allTags,
    filteredSkills,
  } = useSkillFilter(skills);

  const builtinLanguage: BuiltinSkillLanguage =
    i18n.language?.startsWith("zh") ? "zh" : "en";

  const sortedSkills = useMemo(
    () => filteredSkills.slice().sort((a, b) => a.name.localeCompare(b.name)),
    [filteredSkills],
  );
  const hasUnseenBuiltinNotice = useMemo(
    () =>
      Boolean(
        builtinNotice?.has_updates &&
          builtinNotice.fingerprint &&
          builtinNotice.fingerprint !== builtinNoticeAck,
      ),
    [builtinNotice, builtinNoticeAck],
  );
  const builtinNoticeTotal = builtinNotice?.total_changes || 0;

  const confirmOverwrite = useCallback(
    (title: string, content: ReactNode) =>
      new Promise<boolean>((resolve) => {
        Modal.confirm({
          title,
          content,
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
    [t],
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

  const markBuiltinNoticeSeen = useCallback(
    (fingerprint?: string) => {
      const nextFingerprint = String(
        fingerprint || builtinNotice?.fingerprint || "",
      ).trim();
      if (!nextFingerprint) return;
      writeBuiltinNoticeAcknowledgement(nextFingerprint);
      setBuiltinNoticeAck(nextFingerprint);
    },
    [builtinNotice],
  );

  const loadData = useCallback(async (forceReload = false) => {
    if (dataLoadedRef.current && !forceReload) return;

    setLoading(true);
    try {
      const [poolSkills, workspaceSummaries, notice] = await Promise.all([
        api.listSkillPoolSkills(),
        api.listSkillWorkspaces(),
        api.getPoolBuiltinNotice(),
      ]);
      setSkills(poolSkills);
      setWorkspaces(workspaceSummaries);
      setBuiltinNotice(notice);
      dataLoadedRef.current = true;
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "Failed to load skill pool",
      );
    } finally {
      setLoading(false);
    }
  }, [message]);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      invalidateSkillCache({ pool: true, workspaces: true });
      const [poolSkills, workspaceSummaries, notice] = await Promise.all([
        api.refreshSkillPool(),
        api.listSkillWorkspaces(),
        api.getPoolBuiltinNotice(),
      ]);
      setSkills(poolSkills);
      setWorkspaces(workspaceSummaries);
      setBuiltinNotice(notice);
      dataLoadedRef.current = true;
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "Failed to refresh",
      );
    } finally {
      setLoading(false);
    }
  }, [message]);

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
      const [sources, notice] = await Promise.all([
        api.listPoolBuiltinSources(),
        api.getPoolBuiltinNotice(),
      ]);
      setBuiltinSources(sources);
      setBuiltinNotice(notice);
      setImportBuiltinModalOpen(true);
      if (notice.has_updates && notice.fingerprint) {
        markBuiltinNoticeSeen(notice.fingerprint);
      }
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

  const getBuiltinImportStatusLabel = useCallback(
    (status?: string, language?: string) => {
      switch (status) {
        case "outdated":
          return t("skillPool.importStatusOutdated");
        case "language_switch":
          return t("skillPool.importStatusLanguageSwitchTo", {
            language:
              language === "zh"
                ? t("skillPool.langZh")
                : t("skillPool.langEn"),
          });
        case "conflict":
          return t("skillPool.importStatusConflict");
        default:
          return "";
      }
    },
    [t],
  );

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

  const closeDrawer = useCallback(() => {
    setMode(null);
    setActiveSkill(null);
  }, []);

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
      const conflicts: BroadcastConflict[] = [];
      for (const skillName of broadcastSkillNames) {
        try {
          await api.downloadSkillPoolSkill({
            skill_name: skillName,
            targets: targetWorkspaceIds.map((workspace_id) => ({
              workspace_id,
            })),
            preview_only: true,
          });
        } catch (error) {
          if (handleScanError(error, t)) return;
          const detail = parseErrorDetail(error);
          const returnedConflicts = Array.isArray(detail?.conflicts)
            ? detail.conflicts
            : [];
          if (!returnedConflicts.length) {
            throw error;
          }
          conflicts.push(
            ...returnedConflicts.map((conflict) => ({
              skill_name: conflict.skill_name || skillName,
              workspace_id: conflict.workspace_id || "",
              workspace_name:
                conflict.workspace_name ||
                getAgentDisplayName(
                  {
                    id: conflict.workspace_id || "",
                    name:
                      workspaces.find(
                        (workspace) =>
                          workspace.agent_id === conflict.workspace_id,
                      )?.agent_name ?? "",
                  },
                  t,
                ),
              reason:
                conflict.reason === "builtin_upgrade"
                  ? ("builtin_upgrade" as const)
                  : ("conflict" as const),
              current_version_text: conflict.current_version_text || "",
              source_version_text: conflict.source_version_text || "",
            })),
          );
        }
      }
      if (conflicts.length > 0) {
        const allBuiltinUpgrades = conflicts.every(
          (conflict) => conflict.reason === "builtin_upgrade",
        );
        const confirmed = await confirmOverwrite(
          allBuiltinUpgrades
            ? t("skills.builtinUpgradeTitle")
            : t("skillPool.overwriteConfirm"),
          <div style={{ display: "grid", gap: 8 }}>
            <div>
              {allBuiltinUpgrades
                ? t("skillPool.builtinOverwriteTargetsContent")
                : t("skillPool.overwriteTargetsContent")}
            </div>
            {conflicts.map((conflict) => (
              <div
                key={`${conflict.skill_name}-${conflict.workspace_id || ""}`}
              >
                <strong>{conflict.skill_name}</strong>
                {"  "}
                <span>{conflict.workspace_name}</span>
                {conflict.reason === "builtin_upgrade" ? (
                  <>
                    {"  "}
                    {t("skillPool.currentVersion")}:{" "}
                    {conflict.current_version_text || "-"}
                    {"  ->  "}
                    {t("skillPool.sourceVersion")}:{" "}
                    {conflict.source_version_text || "-"}
                  </>
                ) : null}
              </div>
            ))}
          </div>,
        );
        if (!confirmed) return;
      }
      for (const skillName of broadcastSkillNames) {
        const overwriteTargetIds = new Set(
          conflicts
            .filter((conflict) => conflict.skill_name === skillName)
            .map((conflict) => conflict.workspace_id)
            .filter((workspaceId): workspaceId is string =>
              Boolean(workspaceId),
            ),
        );
        const cleanTargetIds = targetWorkspaceIds.filter(
          (workspaceId) => !overwriteTargetIds.has(workspaceId),
        );

        if (cleanTargetIds.length > 0) {
          await api.downloadSkillPoolSkill({
            skill_name: skillName,
            targets: cleanTargetIds.map((workspace_id) => ({
              workspace_id,
            })),
          });
        }

        if (overwriteTargetIds.size > 0) {
          await api.downloadSkillPoolSkill({
            skill_name: skillName,
            targets: Array.from(overwriteTargetIds).map((workspace_id) => ({
              workspace_id,
            })),
            overwrite: true,
          });
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
    selections: BuiltinImportSelection[],
    overwriteConflicts: boolean = false,
  ) => {
    if (selections.length === 0) return;
    try {
      setImportBuiltinLoading(true);
      const result = await api.importSelectedPoolBuiltins({
        imports: selections,
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
                <div key={`${item.skill_name}-${item.language || "en"}`}>
                  <strong>{item.skill_name}</strong>
                  {"  "}
                  {getBuiltinImportStatusLabel(item.status, item.language)}
                  {item.status !== "language_switch" ? (
                    <>
                      {"  "}
                      {t("skillPool.currentVersion")}:{" "}
                      {item.current_version_text || "-"}
                      {"  ->  "}
                      {t("skillPool.sourceVersion")}:{" "}
                      {item.source_version_text || "-"}
                    </>
                  ) : null}
                </div>
              ))}
            </div>
          ),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            await handleImportBuiltins(selections, true);
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

  const handleBuiltinLanguageSwitch = useCallback(
    async (skill: PoolSkillSpec, language: string) => {
      const normalized = language === "zh" ? "zh" : "en";
      if (skill.builtin_language === normalized) return;
      const confirmed = await confirmOverwrite(
        t("skillPool.builtinLanguageChangeTitle"),
        t("skillPool.builtinLanguageChangeContent", {
          name: skill.name,
          language: normalized === "zh" ? t("skillPool.langZh") : t("skillPool.langEn"),
        }),
      );
      if (!confirmed) return;
      try {
        await api.updatePoolBuiltin(skill.name, normalized);
        message.success(
          t("skillPool.builtinLanguageChangeSuccess", {
            name: skill.name,
            language: normalized === "zh" ? t("skillPool.langZh") : t("skillPool.langEn"),
          }),
        );
        closeDrawer();
        invalidateSkillCache({ pool: true });
        await loadData(true);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : t("skillPool.builtinLanguageChangeFailed"),
        );
      }
    },
    [closeDrawer, confirmOverwrite, loadData, message, t],
  );

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

    const persistPoolSkill = async (overwrite = false) => {
      const result =
        mode === "edit"
          ? await api.saveSkillPoolSkill({
              name: skillName,
              content: skillContent,
              source_name: activeSkill?.name,
              config: parsedConfig,
              overwrite,
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
    };

    try {
      await persistPoolSkill();
    } catch (error) {
      if (handleScanError(error, t)) return;
      const detail = parseErrorDetail(error);
      if (mode === "edit" && detail?.reason === "conflict") {
        const confirmed = await confirmOverwrite(
          t("skillPool.overwriteConfirm"),
          <div style={{ display: "grid", gap: 8 }}>
            <div>{t("skills.overwriteExistingList")}</div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              <li>{skillName}</li>
            </ul>
          </div>,
        );
        if (!confirmed) return;
        try {
          await persistPoolSkill(true);
        } catch (retryError) {
          message.error(
            retryError instanceof Error
              ? retryError.message
              : t("common.save") + " failed",
          );
        }
        return;
      }
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
        skill.source === "builtin"
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
    loading,
    skills,
    sortedSkills,
    workspaces,
    mode,
    activeSkill,
    broadcastInitialNames,
    configText,
    zipInputRef,
    importBuiltinModalOpen,
    builtinSources,
    builtinLanguage,
    builtinNotice,
    builtinNoticeTotal,
    hasUnseenBuiltinNotice,
    importBuiltinLoading,
    importModalOpen,
    importing,
    selectedPoolSkills,
    batchModeEnabled,
    viewMode,
    filterOpen,
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allTags,
    form,
    drawerContent,
    showMarkdown,
    conflictRenameModal,
    setImportModalOpen,
    setConfigText,
    setShowMarkdown,
    setFilterOpen,
    setViewMode,
    handleRefresh,
    closeModal,
    openCreate,
    openBroadcast,
    openImportBuiltin,
    closeImportBuiltin,
    closeImportModal,
    openEdit,
    closeDrawer,
    handleDrawerContentChange,
    validateFrontmatter,
    handleBroadcast,
    handleImportBuiltins,
    handleBuiltinLanguageSwitch,
    handleSavePoolSkill,
    handleDelete,
    handleZipImport,
    handleConfirmImport,
    handleBatchDeletePool,
    togglePoolSelect,
    toggleBatchMode,
    selectAllPool,
    clearPoolSelection,
  };
}
