import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";
import {
  Button,
  Checkbox,
  Form,
  Modal,
  Tooltip,
  Switch,
  Select,
} from "@agentscope-ai/design";
import {
  CloseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
  SwapOutlined,
  UploadOutlined,
  UnorderedListOutlined,
  AppstoreOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { PoolSkillSpec, SkillSpec } from "../../../api/types";
import {
  SkillCard,
  SkillDrawer,
  type SkillDrawerFormValues,
  useConflictRenameModal,
  PoolTransferModal,
  SkillFilterDropdown,
  getSkillVisual,
} from "./components";
import { ImportHubModal } from "./components/ImportHubModal";
import { isSkillBuiltin } from "@/utils/skill";
import { useSkills } from "./useSkills";
import { useSkillFilter } from "./useSkillFilter";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import { parseErrorDetail } from "../../../utils/error";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";

dayjs.extend(relativeTime);

type DownloadConflict =
  | {
      skill_name: string;
      reason: "conflict";
    }
  | {
      skill_name: string;
      reason: "builtin_upgrade";
      current_version_text: string;
      source_version_text: string;
    };

function SkillsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
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
    hardRefresh,
  } = useSkills();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillSpec | null>(null);
  const [form] = Form.useForm<SkillDrawerFormValues>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [poolModal, setPoolModal] = useState<"upload" | "download" | null>(
    null,
  );
  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
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

  const toggleSelect = (name: string) => {
    setSelectedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const clearSelection = () => {
    setSelectedSkills(new Set());
  };

  const selectAll = () =>
    setSelectedSkills(new Set(filteredSkills.map((s) => s.name)));

  const MAX_UPLOAD_SIZE_MB = 100;

  const toggleBatchMode = () => {
    if (batchModeEnabled) {
      clearSelection();
      setBatchModeEnabled(false);
    } else {
      setBatchModeEnabled(true);
    }
  };

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
      tags: [],
    });
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
      const saveEditedSkill = async (overwrite = false) => {
        const result = await api.saveSkill({
          name: targetName,
          content: values.content,
          source_name: sourceName !== targetName ? sourceName : undefined,
          config: values.config,
          overwrite,
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
        const detail = parseErrorDetail(error);
        if (detail?.reason === "conflict") {
          const confirmed = await confirmOverwrite(
            t("skillPool.overwriteConfirm"),
            <div style={{ display: "grid", gap: 8 }}>
              <div>{t("skills.overwriteExistingList")}</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>{targetName}</li>
              </ul>
            </div>,
          );
          if (!confirmed) return;
          try {
            await saveEditedSkill(true);
          } catch (retryError) {
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
      const conflictingNames: string[] = [];
      for (const skillName of workspaceSkillNames) {
        try {
          await api.uploadWorkspaceSkillToPool({
            workspace_id: selectedAgent,
            skill_name: skillName,
            preview_only: true,
          });
        } catch (error) {
          const detail = parseErrorDetail(error);
          if (detail?.reason === "conflict") {
            conflictingNames.push(skillName);
            continue;
          }
          throw error;
        }
      }
      if (conflictingNames.length > 0) {
        const confirmed = await confirmOverwrite(
          t("skillPool.overwriteConfirm"),
          <div style={{ display: "grid", gap: 8 }}>
            <div>{t("skills.overwriteExistingList")}</div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {conflictingNames.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </div>,
        );
        if (!confirmed) return;
      }
      for (const skillName of workspaceSkillNames) {
        await api.uploadWorkspaceSkillToPool({
          workspace_id: selectedAgent,
          skill_name: skillName,
          overwrite: conflictingNames.includes(skillName),
        });
      }
      message.success(t("skills.uploadedToPool"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true });
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
      const conflicts: DownloadConflict[] = [];
      for (const skillName of poolSkillNames) {
        try {
          await api.downloadSkillPoolSkill({
            skill_name: skillName,
            targets: [{ workspace_id: selectedAgent }],
            preview_only: true,
          });
        } catch (error) {
          const detail = parseErrorDetail(error);
          const returnedConflicts = Array.isArray(detail?.conflicts)
            ? detail.conflicts
            : [];
          if (!returnedConflicts.length) {
            throw error;
          }
          conflicts.push(
            ...returnedConflicts.map((conflict) =>
              conflict?.reason === "builtin_upgrade"
                ? {
                    skill_name: conflict.skill_name || skillName,
                    reason: "builtin_upgrade" as const,
                    current_version_text: conflict.current_version_text || "",
                    source_version_text: conflict.source_version_text || "",
                  }
                : {
                    skill_name: conflict?.skill_name || skillName,
                    reason: "conflict" as const,
                  },
            ),
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
                : t("skills.overwriteExistingList")}
            </div>
            {conflicts.map((conflict) => (
              <div key={conflict.skill_name}>
                <strong>{conflict.skill_name}</strong>
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
      for (const skillName of poolSkillNames) {
        const shouldOverwrite = conflicts.some(
          (conflict) => conflict.skill_name === skillName,
        );
        await api.downloadSkillPoolSkill({
          skill_name: skillName,
          targets: [{ workspace_id: selectedAgent }],
          overwrite: shouldOverwrite,
        });
      }
      message.success(t("skills.downloadedToWorkspace"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("common.download") + " failed",
      );
    }
  };

  const handleBatchDelete = async () => {
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
    if (!confirmed) return;
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
      message.error(
        error instanceof Error ? error.message : t("skills.batchDeleteFailed"),
      );
    }
  };

  return (
    <div className={styles.skillsPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("skills.title") }]}
        extra={
          <div className={styles.headerRight}>
            <input
              type="file"
              accept=".zip"
              ref={fileInputRef}
              onChange={handleFileChange}
              style={{ display: "none" }}
            />
            {batchModeEnabled ? (
              <div className={styles.batchActions}>
                <>
                  <span className={styles.batchCount}>
                    {t("skills.selectedCount", {
                      count: selectedSkills.size,
                    })}
                  </span>
                  <Button type="default" onClick={selectAll}>
                    {t("skills.selectAll")}
                  </Button>
                  <Button
                    type="default"
                    onClick={clearSelection}
                    icon={<CloseOutlined />}
                  >
                    {t("skills.clearSelection")}
                  </Button>
                  <Tooltip title={t("skills.uploadToPoolHint")}>
                    <Button
                      type="default"
                      className={styles.primaryTransferButton}
                      onClick={() => {
                        const names = Array.from(selectedSkills);
                        if (names.length === 0) return;
                        clearSelection();
                        void handleUploadToPool(names);
                      }}
                      icon={<SwapOutlined />}
                    >
                      {t("skills.uploadToPool")}
                    </Button>
                  </Tooltip>
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    onClick={handleBatchDelete}
                  >
                    {t("common.delete")} ({selectedSkills.size})
                  </Button>
                </>
                <Button type="primary" onClick={toggleBatchMode}>
                  {t("skills.exitBatch")}
                </Button>
              </div>
            ) : (
              <>
                <div className={styles.headerActionsLeft}>
                  <Tooltip title={t("skills.refreshHint")}>
                    <Button
                      type="default"
                      icon={<ReloadOutlined spin={loading} />}
                      onClick={hardRefresh}
                      disabled={loading}
                    />
                  </Tooltip>
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
                  <Button type="primary" onClick={toggleBatchMode}>
                    {t("skills.batchOperation")}
                  </Button>
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
              </>
            )}
          </div>
        }
      />

      <ImportHubModal
        open={importModalOpen}
        importing={importing}
        onCancel={closeImportModal}
        onConfirm={handleConfirmImport}
        cancelImport={cancelImport}
        hint={t("skillPool.externalHubHint")}
      />

      {!loading && skills.length > 0 && (
        <div className={styles.toolbar}>
          <div className={styles.searchContainer}>
            <Select
              mode="multiple"
              className={styles.searchSelect}
              placeholder={t("skills.searchPlaceholder")}
              value={searchTags}
              onChange={setSearchTags}
              searchValue={searchQuery}
              onSearch={setSearchQuery}
              open={filterOpen}
              onDropdownVisibleChange={setFilterOpen}
              allowClear
              maxTagCount="responsive"
              suffixIcon={<SearchOutlined />}
              notFoundContent={<></>}
              dropdownRender={() => (
                <SkillFilterDropdown
                  allTags={allTags}
                  searchTags={searchTags}
                  setSearchTags={setSearchTags}
                  styles={styles}
                />
              )}
            />
          </div>
          <div className={styles.toolbarRight}>
            <div className={styles.viewToggle}>
              <button
                className={`${styles.viewToggleBtn} ${
                  viewMode === "list" ? styles.viewToggleBtnActive : ""
                }`}
                onClick={() => setViewMode("list")}
                title={t("skills.listView")}
              >
                <UnorderedListOutlined />
              </button>
              <button
                className={`${styles.viewToggleBtn} ${
                  viewMode === "card" ? styles.viewToggleBtnActive : ""
                }`}
                onClick={() => setViewMode("card")}
                title={t("skills.gridView")}
              >
                <AppstoreOutlined />
              </button>
            </div>
          </div>
        </div>
      )}

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
              type="primary"
              className={styles.primaryActionButton}
              onClick={handleCreate}
              icon={<PlusOutlined />}
            >
              {t("skills.emptyStateCreate")}
            </Button>
          </div>
        </div>
      ) : viewMode === "card" ? (
        <div className={styles.skillsGrid}>
          {visibleSkills.map((skill) => (
            <SkillCard
              key={skill.name}
              skill={skill}
              selected={
                batchModeEnabled ? selectedSkills.has(skill.name) : undefined
              }
              onSelect={() => toggleSelect(skill.name)}
              onClick={() => handleEdit(skill)}
              onMouseEnter={() => {}}
              onMouseLeave={() => {}}
              onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
              onDelete={(e) => handleDelete(skill, e)}
            />
          ))}
          {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
        </div>
      ) : (
        <div className={styles.skillsList}>
          {visibleSkills.map((skill) => {
            const isBuiltin = isSkillBuiltin(skill.source);
            const channels = (skill.channels || ["all"])
              .map((ch) => (ch === "all" ? t("skills.allChannels") : ch))
              .join(", ");
            const isSelected = selectedSkills.has(skill.name);
            return (
              <div
                key={skill.name}
                className={`${styles.skillListItem} ${
                  isSelected ? styles.selectedListItem : ""
                }`}
                onClick={() => {
                  if (batchModeEnabled) {
                    toggleSelect(skill.name);
                  } else {
                    handleEdit(skill);
                  }
                }}
              >
                {batchModeEnabled && (
                  <Checkbox
                    checked={isSelected}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelect(skill.name);
                    }}
                  />
                )}
                <div className={styles.listItemLeft}>
                  <span className={styles.fileIcon}>
                    {getSkillVisual(skill.name, skill.emoji)}
                  </span>
                  <div className={styles.listItemInfo}>
                    <div className={styles.listItemHeader}>
                      <span className={styles.skillTitle}>{skill.name}</span>
                      <span className={styles.typeBadge}>
                        {isBuiltin ? t("skills.builtin") : t("skills.custom")}
                      </span>
                      <span className={styles.channelBadge}>{channels}</span>
                      {skill.last_updated && (
                        <span className={styles.listItemTime}>
                          {t("skills.lastUpdated")}{" "}
                          {dayjs(skill.last_updated).fromNow()}
                        </span>
                      )}
                    </div>
                    <p className={styles.listItemDesc}>
                      {skill.description || "-"}
                    </p>
                    {!!skill.tags?.length && (
                      <div className={styles.listItemTags}>
                        {skill.tags.map((tag) => (
                          <span key={tag} className={styles.tagChip}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className={styles.listItemRight}>
                  <span onClick={(e) => e.stopPropagation()}>
                    <Switch
                      checked={skill.enabled}
                      disabled={batchModeEnabled}
                      onChange={async () => {
                        await toggleEnabled(skill);
                        await refreshSkills();
                      }}
                    />
                  </span>
                  <Button
                    danger
                    disabled={batchModeEnabled}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(skill);
                    }}
                  >
                    {t("common.delete")}
                  </Button>
                </div>
              </div>
            );
          })}
          {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
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
        availableTags={allTags}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default SkillsPage;
