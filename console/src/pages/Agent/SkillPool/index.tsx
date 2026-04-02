import { useEffect, useRef, useState } from "react";
import { Button, Input, Tooltip } from "@agentscope-ai/design";
import {
  AppstoreOutlined,
  CloseOutlined,
  DeleteOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SendOutlined,
  SyncOutlined,
  UnorderedListOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { ImportHubModal } from "../Skills/components";
import { PageHeader } from "@/components/PageHeader";
import {
  BroadcastModal,
  ImportBuiltinModal,
  SkillPoolCard,
  SkillPoolListItem,
  SkillPoolDrawer,
} from "./components";
import { useSkillPool } from "./hooks/useSkillPool";
import styles from "./index.module.less";

function SkillPoolPage() {
  const { t } = useTranslation();
  const zipInputRef = useRef<HTMLInputElement>(null);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [searchQuery, setSearchQuery] = useState("");

  const {
    // State
    skills,
    workspaces,
    loading,
    mode,
    activeSkill,
    selectedPoolSkills,
    poolBatchMode,
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
    handleZipImport,
    handleSavePoolSkill,
    validateFrontmatter,
  } = useSkillPool();

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredSkills = skills.filter(
    (skill) =>
      skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (skill.description || "")
        .toLowerCase()
        .includes(searchQuery.toLowerCase()),
  );

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
            {poolBatchMode ? (
              <>
                <div className={styles.batchActions}>
                  <span className={styles.batchCount}>
                    {t("skills.selectedCount", {
                      count: selectedPoolSkills.size,
                    })}
                  </span>
                  <Button type="default" onClick={selectAllPool}>
                    {t("skills.selectAll")}
                  </Button>
                  <Button
                    type="default"
                    onClick={clearPoolSelection}
                    icon={<CloseOutlined />}
                  >
                    {t("skills.clearSelection")}
                  </Button>
                  <Button
                    danger
                    type="primary"
                    icon={<DeleteOutlined />}
                    onClick={handleBatchDeletePool}
                  >
                    {t("common.delete")} ({selectedPoolSkills.size})
                  </Button>
                </div>
                <Button type="primary" onClick={toggleBatchMode}>
                  {t("skills.exitBatch")}
                </Button>
              </>
            ) : (
              <>
                <div className={styles.headerActionsLeft}>
                  <Tooltip title={t("skillPool.refreshHint")}>
                    <Button
                      type="default"
                      icon={<ReloadOutlined spin={loading} />}
                      onClick={handleRefresh}
                      disabled={loading}
                    />
                  </Tooltip>
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
                  <Button type="primary" onClick={toggleBatchMode}>
                    {t("skills.batchOperation")}
                  </Button>
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
              </>
            )}
          </div>
        }
      />

      {/* ---- Scrollable Content ---- */}
      <div className={styles.content}>
        {/* Toolbar */}
        <div className={styles.toolbar}>
          <Input
            className={styles.searchInput}
            placeholder={t("skills.searchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            allowClear
            prefix={<SearchOutlined />}
          />
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

        {loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("common.loading")}</span>
          </div>
        ) : viewMode === "card" ? (
          <div className={styles.skillsGrid}>
            {filteredSkills.map((skill) => (
              <SkillPoolCard
                key={skill.name}
                skill={skill}
                isSelected={selectedPoolSkills.has(skill.name)}
                batchMode={poolBatchMode}
                onToggleSelect={togglePoolSelect}
                onEdit={openEdit}
                onBroadcast={openBroadcast}
                onDelete={handleDelete}
              />
            ))}
          </div>
        ) : (
          <div className={styles.skillsList}>
            {filteredSkills.map((skill) => (
              <SkillPoolListItem
                key={skill.name}
                skill={skill}
                isSelected={selectedPoolSkills.has(skill.name)}
                batchMode={poolBatchMode}
                onToggleSelect={togglePoolSelect}
                onEdit={openEdit}
                onBroadcast={openBroadcast}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>

      <ImportHubModal
        open={importModalOpen}
        importing={importing}
        onCancel={closeImportModal}
        onConfirm={handleConfirmImport}
        hint={t("skillPool.externalHubHint")}
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

      <SkillPoolDrawer
        mode={mode}
        activeSkill={activeSkill}
        onClose={closeDrawer}
        onSave={handleSavePoolSkill}
        validateFrontmatter={validateFrontmatter}
      />

      {conflictRenameModal}
    </div>
  );
}

export default SkillPoolPage;
