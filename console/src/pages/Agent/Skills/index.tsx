import { useEffect, useRef, useState, useMemo } from "react";
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
  ImportHubModal,
  PoolTransferModal,
  SkillFilterDropdown,
  getSkillVisual,
  getSkillDisplaySource,
} from "./components";
import { useSkills } from "./useSkills";
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
  const [hoverKey, setHoverKey] = useState<string | null>(null);
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
  const batchMode = batchModeEnabled;
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTags, setSearchTags] = useState<string[]>([]);

  // Extract all unique categories and tags from skills
  const allCategories = useMemo(
    () =>
      Array.from(
        new Set(skills.flatMap((skill) => skill.categories || [])),
      ).sort(),
    [skills],
  );
  const allTags = useMemo(
    () =>
      Array.from(new Set(skills.flatMap((skill) => skill.tags || []))).sort(),
    [skills],
  );

  // Parse search tags to separate categories and tags
  const selectedCategories = useMemo(
    () =>
      searchTags
        .filter((tag) => tag.startsWith("📂:"))
        .map((tag) => tag.replace(/^📂:/, "")),
    [searchTags],
  );
  const selectedTags = useMemo(
    () =>
      searchTags
        .filter((tag) => tag.startsWith("🏷️:"))
        .map((tag) => tag.replace(/^🏷️:/, "")),
    [searchTags],
  );

  const filteredSkills = useMemo(() => {
    const query = searchQuery.toLowerCase();
    return skills.filter((skill) => {
      // Text search filter
      const matchesText =
        !query ||
        skill.name.toLowerCase().includes(query) ||
        (skill.description && skill.description.toLowerCase().includes(query));

      // Category filter
      const matchesCategory =
        selectedCategories.length === 0 ||
        selectedCategories.some((cat) => skill.categories?.includes(cat));

      // Tag filter
      const matchesTag =
        selectedTags.length === 0 ||
        selectedTags.some((tag) => skill.tags?.includes(tag));

      return matchesText && matchesCategory && matchesTag;
    });
  }, [skills, searchQuery, selectedCategories, selectedTags]);

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
    // setBatchModeEnabled(false);
  };

  const selectAll = () => setSelectedSkills(new Set(skills.map((s) => s.name)));

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
      invalidateSkillCache({ agentId: selectedAgent, pool: true });
      await refreshSkills();
      setPoolSkills(await api.listSkillPoolSkills());
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    }
  };

  const handleDownloadFromPool = async (
    poolSkillNames: string[],
    overwrite?: boolean,
  ) => {
    if (poolSkillNames.length === 0) return;
    try {
      for (const skillName of poolSkillNames) {
        let targetName: string | undefined;
        let shouldOverwrite = overwrite;
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
              overwrite: shouldOverwrite,
            });
            break;
          } catch (error) {
            const detail = parseErrorDetail(error);
            const conflict = detail?.conflicts?.[0];
            if (conflict?.reason === "builtin_upgrade") {
              const confirmed = await new Promise<boolean>((resolve) => {
                Modal.confirm({
                  title: t("skills.builtinUpgradeTitle"),
                  content: t("skills.builtinUpgradeContent", {
                    name: conflict.skill_name || skillName,
                  }),
                  onOk: () => resolve(true),
                  onCancel: () => resolve(false),
                });
              });
              if (!confirmed) return;
              shouldOverwrite = true;
              continue;
            }
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
            {batchMode ? (
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
              mode="tags"
              className={styles.searchSelect}
              placeholder={t("skills.searchPlaceholder")}
              value={searchTags}
              onChange={(values) =>
                setSearchTags(
                  values.filter(
                    (v) => v.startsWith("📂:") || v.startsWith("🏷️:"),
                  ),
                )
              }
              searchValue={searchQuery}
              onSearch={setSearchQuery}
              allowClear
              maxTagCount="responsive"
              suffixIcon={<SearchOutlined />}
              dropdownRender={() => (
                <SkillFilterDropdown
                  allCategories={allCategories}
                  allTags={allTags}
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
          {filteredSkills
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
                selected={
                  batchMode ? selectedSkills.has(skill.name) : undefined
                }
                onSelect={() => toggleSelect(skill.name)}
                onClick={() => handleEdit(skill)}
                onMouseEnter={() => setHoverKey(skill.name)}
                onMouseLeave={() => setHoverKey(null)}
                onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
                onDelete={(e) => handleDelete(skill, e)}
              />
            ))}
        </div>
      ) : (
        <div className={styles.skillsList}>
          {filteredSkills
            .slice()
            .sort((a, b) => {
              if (a.enabled && !b.enabled) return -1;
              if (!a.enabled && b.enabled) return 1;
              return a.name.localeCompare(b.name);
            })
            .map((skill) => {
              const isBuiltin =
                getSkillDisplaySource(skill.source) === "builtin";
              const channels = skill.channels?.join(", ") || "all";
              const isSelected = selectedSkills.has(skill.name);
              return (
                <div
                  key={skill.name}
                  className={`${styles.skillListItem} ${
                    isSelected ? styles.selectedListItem : ""
                  }`}
                  onClick={() => {
                    if (batchMode) {
                      toggleSelect(skill.name);
                    } else {
                      handleEdit(skill);
                    }
                  }}
                >
                  {batchMode && (
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
                    </div>
                  </div>
                  <div className={styles.listItemRight}>
                    <Switch
                      checked={skill.enabled}
                      disabled={batchMode}
                      onChange={async () => {
                        await toggleEnabled(skill);
                        await refreshSkills();
                      }}
                    />
                    <Button
                      danger
                      disabled={batchMode}
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
    </div>
  );
}

export default SkillsPage;
