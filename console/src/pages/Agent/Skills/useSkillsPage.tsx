import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Form } from "@agentscope-ai/design";
import type { SkillDetail, SkillSpec, PoolSkillSpec } from "../../../api/types";
import type { SkillDrawerFormValues } from "./components";
import { useConflictRenameModal } from "./components";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { createSkillGovernanceApi } from "@/api/modules/skillGovernance";
import type {
  SkillCatalogItem,
  SkillPreview,
} from "@/api/types/skillGovernance";
import {
  useSkillRuntime,
  confirmSkillAction,
  skillErrorMessage,
} from "./useSkillRuntime";
import { useUploadLimitStore } from "../../../stores/uploadLimitStore";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type { SecurityScanErrorResponse } from "../../../api/modules/security";
import { parseErrorDetail } from "../../../utils/error";
import {
  checkScanWarnings as checkScanWarningsShared,
  showScanErrorModal,
} from "../../../utils/scanError";
import { useSkills } from "./useSkills";
import { useSkillFilter } from "./useSkillFilter";

// ─── Types ──────────────────────────────────────────────────────────────────

export type DownloadConflict =
  | { skill_name: string; reason: "conflict" }
  | {
      skill_name: string;
      reason: "builtin_upgrade";
      current_version_text: string;
      source_version_text: string;
    }
  | {
      skill_name: string;
      reason: "language_switch";
      source_language: string;
      current_language: string;
    };

type AdminPoolDraft = PoolSkillSpec & SkillPreview;
type PoolEntry = SkillCatalogItem | PoolSkillSpec | AdminPoolDraft;

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useSkillsPage() {
  const { t } = useTranslation();
  const { scope, api, message, modal: Modal } = useSkillRuntime();
  const governance = useMemo(() => createSkillGovernanceApi(scope), [scope]);
  const { selectedAgent } = useAgentStore();

  const {
    skills,
    providerSkills,
    loading,
    uploading,
    importing,
    readOnly,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    refreshSkills,
    hardRefresh,
  } = useSkills();

  const {
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allTags,
    filteredSkills,
  } = useSkillFilter(skills);

  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  // ── Local state ─────────────────────────────────────────────────────────

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillDetail | null>(null);
  const [editingSkillName, setEditingSkillName] = useState("");
  const [drawerLoading, setDrawerLoading] = useState(false);
  const detailRequestIdRef = useRef(0);
  const [form] = Form.useForm<SkillDrawerFormValues>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [poolError, setPoolError] = useState("");
  const [publicationResult, setPublicationResult] = useState<{
    submitted: string[];
    pending: string[];
    error: string;
  } | null>(null);
  const [poolLoading, setPoolLoading] = useState(false);
  const [poolBusy, setPoolBusy] = useState(false);
  const poolBusyRef = useRef(false);
  const [poolSkills, setPoolSkills] = useState<PoolEntry[]>([]);
  const [poolModal, setPoolModal] = useState<"upload" | "download" | null>(
    null,
  );
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
  const [batchModeEnabled, setBatchModeEnabled] = useState(false);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [filterOpen, setFilterOpen] = useState(false);

  // ── Derived ─────────────────────────────────────────────────────────────

  const sortedSkills = useMemo(
    () =>
      filteredSkills.slice().sort((a, b) => {
        if (a.enabled && !b.enabled) return -1;
        if (!a.enabled && b.enabled) return 1;
        return a.name.localeCompare(b.name);
      }),
    [filteredSkills],
  );

  const {
    visibleItems: visibleSkills,
    hasMore,
    sentinelRef,
  } = useProgressiveRender(sortedSkills);

  // ── Effects ─────────────────────────────────────────────────────────────

  useEffect(() => {
    setPoolSkills([]);
    setPoolError("");
    setPoolLoading(false);
    if (poolModal !== "download" || !scope.canEdit) return;
    let active = true;
    setPoolLoading(true);
    const loadPoolSkills = async (): Promise<PoolEntry[]> => {
      if (!scope.multiUser) return api.listSkillPoolSkills();
      if (!scope.isAdmin) return (await governance.catalog()).items;

      const [preview, registered] = await Promise.all([
        governance.preview(),
        governance.items(),
      ]);
      const registeredByName = new Map(
        registered.items.map((item) => [item.name, item]),
      );
      return preview.items.reduce<PoolEntry[]>((result, candidate) => {
        const item = registeredByName.get(candidate.name);
        if (item?.status === "disabled") return result;
        result.push(
          item?.content_hash === candidate.content_hash
            ? item
            : { ...candidate, source: "custom" },
        );
        return result;
      }, []);
    };
    void loadPoolSkills()
      .then((data) => {
        if (active && scope.current()) setPoolSkills(data);
      })
      .catch((error) => {
        if (active && scope.current())
          setPoolError(skillErrorMessage(error, t));
      })
      .finally(() => {
        if (active && scope.current()) setPoolLoading(false);
      });
    return () => {
      active = false;
    };
  }, [poolModal, governance, scope, api, t]);

  // ── Helpers ─────────────────────────────────────────────────────────────

  const confirmOverwrite = (title: string, content: ReactNode) =>
    new Promise<boolean>((resolve) => {
      Modal.confirm({
        title,
        content,
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

  const checkScanWarnings = async (skillName: string) => {
    if (!scope.current()) return;
    await checkScanWarningsShared(
      skillName,
      api.getBlockedHistory,
      api.getSkillScanner,
      t,
      scope,
    );
  };

  const toggleSelect = (name: string) => {
    setSelectedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const clearSelection = () => setSelectedSkills(new Set());

  const selectAll = () =>
    setSelectedSkills(new Set(filteredSkills.map((s) => s.name)));

  const toggleBatchMode = () => {
    if (batchModeEnabled) {
      clearSelection();
      setBatchModeEnabled(false);
    } else {
      setBatchModeEnabled(true);
    }
  };

  const closePoolModal = () => setPoolModal(null);

  const handleUploadClick = () => fileInputRef.current?.click();

  // ── File upload ─────────────────────────────────────────────────────────

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }
    const sizeMB = file.size / (1024 * 1024);
    const uploadLimit = useUploadLimitStore.getState().uploadMaxSizeMb;
    if (uploadLimit !== null && sizeMB > uploadLimit) {
      message.warning(
        t("skills.fileSizeExceeded", {
          limit: uploadLimit,
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
      if (!newRenames || !scope.current()) break;
      renameMap = { ...renameMap, ...newRenames };
    }
  };

  // ── Create / Edit / Delete ──────────────────────────────────────────────

  const handleCreate = () => {
    if (!scope.current() || !scope.canEdit) return;
    detailRequestIdRef.current += 1;
    setEditingSkill(null);
    setEditingSkillName("");
    setDrawerLoading(false);
    form.resetFields();
    form.setFieldsValue({ enabled: false, channels: ["all"], tags: [] });
    setDrawerOpen(true);
  };

  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
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
        if (renameMap && scope.current()) {
          const newName = Object.values(renameMap)[0];
          if (newName) await handleConfirmImport(url, newName);
        }
      }
    }
  };

  const handleEdit = async (skill: SkillSpec) => {
    if (!scope.current() || !scope.canEdit) return;
    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setEditingSkill(null);
    setEditingSkillName(skill.name);
    setDrawerLoading(true);
    form.resetFields();
    setDrawerOpen(true);
    try {
      const detail = await api.getSkill(skill.name, selectedAgent);
      if (detailRequestIdRef.current !== requestId) return;
      setEditingSkill(detail);
    } catch (error) {
      if (!scope.current()) return;
      if (detailRequestIdRef.current !== requestId) return;
      message.error(
        error instanceof Error ? error.message : t("skills.loadFailed"),
      );
      setDrawerOpen(false);
      setEditingSkillName("");
    } finally {
      if (detailRequestIdRef.current === requestId) {
        setDrawerLoading(false);
      }
    }
  };

  const handleToggleEnabled = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    await toggleEnabled(skill);
    await refreshSkills();
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteSkill(skill);
  };

  const handleDrawerClose = () => {
    detailRequestIdRef.current += 1;
    setDrawerOpen(false);
    setEditingSkill(null);
    setEditingSkillName("");
    setDrawerLoading(false);
  };

  // ── Drawer submit ───────────────────────────────────────────────────────

  const handleSubmit = async (values: SkillDetail) => {
    if (!scope.current() || !scope.canEdit) return;
    if (editingSkill) {
      const sourceName = editingSkill.name;
      const targetName = values.name;
      const saveEditedSkill = async (overwrite = false, expectedHash?: string) => {
        const result = await api.saveSkill({
          name: targetName,
          content: values.content,
          source_name: sourceName !== targetName ? sourceName : undefined,
          config: values.config,
          overwrite,
          ...(expectedHash ? { expected_content_hash: expectedHash } : {}),
        });
        const sideUpdates: Promise<unknown>[] = [];
        const newChannels = values.channels || ["all"];
        if (
          JSON.stringify(newChannels) !==
          JSON.stringify(editingSkill.channels || ["all"])
        ) {
          sideUpdates.push(api.updateSkillChannels(result.name, newChannels));
        }
        const newTags = values.tags || [];
        if (
          JSON.stringify(newTags) !== JSON.stringify(editingSkill.tags || [])
        ) {
          sideUpdates.push(api.updateSkillTags(result.name, newTags));
        }
        await Promise.all(sideUpdates);
        if (result.mode === "noop" && sideUpdates.length === 0) {
          setDrawerOpen(false);
          return;
        }
        if (result.mode !== "noop") {
          message.success(
            result.mode === "rename"
              ? `${t("common.save")}: ${result.name}`
              : t("common.save"),
          );
        }
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
        await refreshSkills();
      };
      try {
        await saveEditedSkill();
      } catch (error) {
        if (!scope.current()) return;
        const detail = parseErrorDetail(error);
        if (detail?.reason === "conflict") {
          const confirmed = await confirmOverwrite(
            t("skillPool.overwriteConfirm"),
            <div style={{ display: "grid", gap: 8 }}>
              <div>{t("skills.overwriteExistingList")}</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>{targetName}</li>
              </ul>
              <code>{detail.expected_content_hash}</code>
            </div>,
          );
          if (!confirmed || !scope.current()) return;
          try {
            await saveEditedSkill(true, detail.expected_content_hash);
          } catch (retryError) {
            if (!scope.current()) return;
            message.error(
              retryError instanceof Error
                ? retryError.message
                : t("common.save"),
            );
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
        const actualName = result.name || submitName;
        await Promise.all([
          api.updateSkillChannels(actualName, values.channels || ["all"]),
          ...(values.tags?.length
            ? [api.updateSkillTags(actualName, values.tags)]
            : []),
        ]);
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
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
        if (renameMap && scope.current()) {
          const newName = Object.values(renameMap)[0];
          if (newName) await handleSubmit({ ...values, name: newName });
        }
      }
    }
  };

  // ── Pool transfer ───────────────────────────────────────────────────────

  const legacyTransfer = async (names: string[], upload: boolean) => {
    if (!scope.current() || !scope.canEdit || poolBusyRef.current) return;
    poolBusyRef.current = true;
    setPoolBusy(true);
    setPoolError("");
    const transfer = (name: string, preview: boolean, overwrite: boolean) => upload
      ? api.uploadWorkspaceSkillToPool({ workspace_id: scope.agentId, skill_name: name, preview_only: preview, overwrite })
      : api.downloadSkillPoolSkill({ skill_name: name, targets: [{ workspace_id: scope.agentId }], preview_only: preview, overwrite });
    try {
      const conflicts = new Map<string, string>();
      for (const name of names) {
        scope.assert();
        try { await transfer(name, true, false); }
        catch (error) {
          scope.assert();
          const detail = parseErrorDetail(error);
          if (detail?.reason !== "conflict" && !detail?.conflicts?.length) throw error;
          conflicts.set(name, JSON.stringify(detail));
        }
      }
      if (conflicts.size && !await confirmOverwrite(t("skillPool.overwriteConfirm"),
        <div>{[...conflicts].map(([name, detail]) => <p key={name}>{name}: {detail}</p>)}</div>)) return;
      for (const name of names) {
        scope.assert();
        await transfer(name, false, conflicts.has(name));
      }
      scope.assert();
      closePoolModal();
      invalidateSkillCache({ pool: upload, agentId: scope.agentId });
      await refreshSkills();
      message.success(t("skillGovernance.completed"));
    } catch (error) {
      if (scope.current()) setPoolError(skillErrorMessage(error, t));
    } finally {
      if (scope.current()) { setPoolBusy(false); poolBusyRef.current = false; }
    }
  };

  const handleUploadToPool = async (workspaceSkillNames: string[]) => {
    if (!scope.multiUser) return legacyTransfer(workspaceSkillNames, true);
    if (!scope.current() || !scope.canSubmit || poolBusyRef.current) return;
    const names = workspaceSkillNames.filter((name) =>
      skills.some(
        (skill) => skill.name === name && !skill.source_pool_version_id,
      ),
    );
    if (!names.length) return;
    poolBusyRef.current = true;
    setPoolBusy(true);
    setPoolError("");
    setPublicationResult(null);
    const submitted: string[] = [];
    let failure = "";
    try {
      for (const name of names) {
        scope.assert();
        await governance.submit(name);
        scope.assert();
        submitted.push(name);
      }
      if (scope.current()) {
        message.success(t("skillGovernance.submitted"));
        closePoolModal();
      }
    } catch (error) {
      if (!scope.current()) return;
      failure = skillErrorMessage(error, t);
      setPoolError(failure);
    } finally {
      if (scope.current()) {
        setSelectedSkills(
          (previous) =>
            new Set([...previous].filter((name) => !submitted.includes(name))),
        );
        setPublicationResult({
          submitted,
          pending: names.filter((name) => !submitted.includes(name)),
          error: failure,
        });
        setPoolBusy(false);
        poolBusyRef.current = false;
      }
    }
  };

  const handleDownloadFromPool = async (names: string[]) => {
    if (!scope.multiUser) return legacyTransfer(names, false);
    if (
      !scope.current() ||
      !scope.canEdit ||
      poolBusyRef.current ||
      !names.length
    )
      return;
    const selected = poolSkills.filter((item) => names.includes(item.name));
    if (selected.length !== names.length) return;
    poolBusyRef.current = true;
    setPoolBusy(true);
    setPoolError("");
    try {
      let catalogItems = selected.filter(
        (item): item is SkillCatalogItem => "id" in item,
      );
      if (scope.isAdmin) {
        const drafts = selected
          .filter(
            (item): item is AdminPoolDraft =>
              !("id" in item) && "content_hash" in item,
          )
          .map(({ name, content_hash }) => ({ name, content_hash }));
        if (drafts.length) {
          await governance.register(drafts);
          scope.assert();
        }
        const registered = (await governance.items()).items;
        scope.assert();
        catalogItems = registered.filter(
          (item) => item.status === "active" && names.includes(item.name),
        );
        if (catalogItems.length !== names.length) {
          setPoolError(t("skillGovernance.draft"));
          return;
        }
        for (const item of catalogItems) {
          await governance.grant(item.id, scope.agentId, true);
          scope.assert();
        }
      }
      if (catalogItems.length !== names.length) return;
      // Confirm every known collision before starting any writes.
      const hashes = new Map<string, string>();
      for (const item of catalogItems) {
        const existing = skills.find((skill) => skill.name === item.name);
        if (!existing) continue;
        if (!existing.content_hash) {
          setPoolError(t("skillGovernance.conflict"));
          invalidateSkillCache({ agentId: scope.agentId });
          await refreshSkills();
          return;
        }
        const confirmed = await confirmSkillAction(scope, Modal, {
          title: t("skillPool.overwriteConfirm"),
          content: (
            <div>
              <p>
                {t("skillGovernance.overwriteWarning", { name: item.name })}
              </p>
              <code>{existing.content_hash}</code>
            </div>
          ),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
        });
        if (!confirmed || !scope.current()) return;
        hashes.set(item.id, existing.content_hash);
      }
      for (const item of catalogItems) {
        scope.assert();
        await governance.load(item.id, hashes.get(item.id));
      }
      if (!scope.current()) return;
      message.success(t("skillGovernance.completed"));
      closePoolModal();
      invalidateSkillCache({ agentId: scope.agentId });
      await refreshSkills();
    } catch (error) {
      if (!scope.current()) return;
      setPoolError(skillErrorMessage(error, t));
      invalidateSkillCache({ agentId: scope.agentId });
      await refreshSkills();
    } finally {
      if (scope.current()) {
        setPoolBusy(false);
        poolBusyRef.current = false;
      }
    }
  };

  // ── Batch enable / disable ───────────────────────────────────────────────

  const handleBatchEnable = async () => {
    if (!scope.current() || !scope.canEdit) return;
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    try {
      const { results } = await api.batchEnableSkills(names);
      const entries = Object.entries(results);
      const succeeded = entries
        .filter(([, r]) => r.success)
        .map(([name]) => name);
      const failed = entries.filter(([, r]) => r.success === false);
      for (const [, result] of failed) {
        const detail = result.detail;
        if (result.reason !== "security_scan_failed" || !detail) continue;
        showScanErrorModal(detail as SecurityScanErrorResponse, t, scope);
      }
      if (failed.length > 0) {
        message.warning(
          t("skills.batchEnablePartial", {
            enabled: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchEnableSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
      for (const name of succeeded) {
        await checkScanWarnings(name);
      }
    } catch (error) {
      if (!scope.current()) return;
      message.error(
        error instanceof Error ? error.message : t("skills.batchEnableFailed"),
      );
    }
  };

  const handleBatchDisable = async () => {
    if (!scope.current() || !scope.canEdit) return;
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    try {
      const { results } = await api.batchDisableSkills(names);
      const failed = Object.entries(results).filter(([, r]) => !r.success);
      if (failed.length > 0) {
        message.warning(
          t("skills.batchDisablePartial", {
            disabled: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchDisableSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      if (!scope.current()) return;
      message.error(
        error instanceof Error ? error.message : t("skills.batchDisableFailed"),
      );
    }
  };

  // ── Batch delete ────────────────────────────────────────────────────────

  const handleBatchDelete = async () => {
    if (!scope.current() || !scope.canEdit) return;
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("skills.batchDeleteTitle", { count: names.length }),
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
    if (!confirmed || !scope.current()) return;
    try {
      const { results } = await api.batchDeleteSkills(names);
      const failed = Object.entries(results).filter(([, r]) => !r.success);
      if (failed.length > 0) {
        message.warning(
          t("skills.batchDeletePartial", {
            deleted: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchDeleteSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      if (!scope.current()) return;
      message.error(
        error instanceof Error ? error.message : t("skills.batchDeleteFailed"),
      );
    }
  };

  return {
    skills,
    providerSkills,
    sortedSkills,
    visibleSkills,
    hasMore,
    sentinelRef,
    poolSkills,
    poolError,
    publicationResult,
    poolLoading,
    poolBusy,
    canSubmit: scope.multiUser ? scope.canSubmit : scope.canEdit,
    multiUser: scope.multiUser,
    allTags,
    filteredSkills,
    conflictRenameModal,
    loading,
    uploading,
    importing,
    readOnly,
    drawerOpen,
    drawerLoading,
    editingSkillName,
    importModalOpen,
    setImportModalOpen,
    editingSkill,
    form,
    fileInputRef,
    poolModal,
    setPoolModal,
    selectedSkills,
    batchModeEnabled,
    viewMode,
    setViewMode,
    filterOpen,
    setFilterOpen,
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    handleCreate,
    handleEdit,
    handleToggleEnabled,
    handleDelete,
    handleDrawerClose,
    handleSubmit,
    handleUploadToPool,
    handleDownloadFromPool,
    handleBatchEnable,
    handleBatchDisable,
    handleBatchDelete,
    handleUploadClick,
    handleFileChange,
    handleConfirmImport,
    closeImportModal,
    closePoolModal,
    toggleSelect,
    clearSelection,
    selectAll,
    toggleBatchMode,
    toggleEnabled,
    refreshSkills,
    hardRefresh,
    cancelImport,
  };
}
