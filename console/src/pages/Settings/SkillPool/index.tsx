import { Button, Select, Tooltip } from "@agentscope-ai/design";
import { Badge } from "antd";
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
import { ImportHubModal } from "../../Agent/Skills/components/ImportHubModal";
import { SkillFilterDropdown } from "../../Agent/Skills/components/SkillFilterDropdown";
import {
  BroadcastModal,
  ImportBuiltinModal,
  PoolSkillCard,
  PoolSkillListItem,
  PoolSkillDrawer,
} from "./components";
import { getBuiltinNoticeLines } from "./builtinNotice";
import { useSkillPool } from "./useSkillPool";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";
import { PageHeader } from "@/components/PageHeader";
import type { PoolSkillSpec } from "../../../api/types";
import styles from "./index.module.less";

function SkillPoolPage() {
  const { t } = useTranslation();
  const pool = useSkillPool();
  const builtinNoticeLines = getBuiltinNoticeLines(pool.builtinNotice, t);
  const {
    visibleItems: visibleSkills,
    hasMore,
    sentinelRef,
  } = useProgressiveRender(pool.sortedSkills);

  return (
    <div className={styles.skillsPage}>
      <PageHeader
        items={[{ title: t("nav.settings") }, { title: t("nav.skillPool") }]}
        extra={
          <div className={styles.headerRight}>
            <input
              type="file"
              accept=".zip"
              ref={pool.zipInputRef}
              onChange={pool.handleZipImport}
              style={{ display: "none" }}
            />
            {pool.batchModeEnabled ? (
              <div className={styles.batchActions}>
                <span className={styles.batchCount}>
                  {t("skills.selectedCount", {
                    count: pool.selectedPoolSkills.size,
                  })}
                </span>
                <Button type="default" onClick={pool.selectAllPool}>
                  {t("skills.selectAll")}
                </Button>
                <Button
                  type="default"
                  onClick={pool.clearPoolSelection}
                  icon={<CloseOutlined />}
                >
                  {t("skills.clearSelection")}
                </Button>
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  onClick={pool.handleBatchDeletePool}
                >
                  {t("common.delete")} ({pool.selectedPoolSkills.size})
                </Button>
                <Button type="primary" onClick={pool.toggleBatchMode}>
                  {t("skills.exitBatch")}
                </Button>
              </div>
            ) : (
              <>
                <div className={styles.headerActionsLeft}>
                  <Tooltip title={t("skillPool.refreshHint")}>
                    <Button
                      type="default"
                      icon={<ReloadOutlined spin={pool.loading} />}
                      onClick={pool.handleRefresh}
                      disabled={pool.loading}
                    />
                  </Tooltip>
                  <Tooltip title={t("skillPool.broadcastHint")}>
                    <Button
                      type="default"
                      className={styles.primaryTransferButton}
                      icon={<SendOutlined />}
                      onClick={() => pool.openBroadcast()}
                    >
                      {t("skillPool.broadcast")}
                    </Button>
                  </Tooltip>
                  <Tooltip
                    title={
                      pool.hasUnseenBuiltinNotice
                        ? builtinNoticeLines.length > 0
                          ? builtinNoticeLines.map((line) => (
                              <div key={line}>{line}</div>
                            ))
                          : t("skillPool.importBuiltinAlertHint", {
                              count: pool.builtinNoticeTotal,
                            })
                        : t("skillPool.importBuiltinHint")
                    }
                  >
                    <Badge
                      dot={pool.hasUnseenBuiltinNotice}
                      color="rgba(255, 157, 77, 1)"
                      offset={[-4, 4]}
                    >
                      <Button
                        type="default"
                        icon={<SyncOutlined />}
                        onClick={() => void pool.openImportBuiltin()}
                      >
                        {t("skillPool.importBuiltin")}
                      </Button>
                    </Badge>
                  </Tooltip>
                </div>
                <div className={styles.headerActionsRight}>
                  <Tooltip title={t("skillPool.uploadZipHint")}>
                    <Button
                      type="default"
                      icon={<UploadOutlined />}
                      onClick={() => pool.zipInputRef.current?.click()}
                    >
                      {t("skills.uploadZip")}
                    </Button>
                  </Tooltip>
                  <Tooltip title={t("skillPool.importHubHint")}>
                    <Button
                      type="default"
                      icon={<ImportOutlined />}
                      onClick={() => pool.setImportModalOpen(true)}
                    >
                      {t("skills.importHub")}
                    </Button>
                  </Tooltip>
                  <Button type="primary" onClick={pool.toggleBatchMode}>
                    {t("skills.batchOperation")}
                  </Button>
                  <Tooltip title={t("skills.createSkillHint")}>
                    <Button
                      type="primary"
                      className={styles.primaryActionButton}
                      icon={<PlusOutlined />}
                      onClick={pool.openCreate}
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
        {!pool.loading && pool.skills.length > 0 && (
          <div className={styles.toolbar}>
            <div className={styles.searchContainer}>
              <Select
                mode="multiple"
                className={styles.searchSelect}
                placeholder={t("skills.searchPlaceholder")}
                value={pool.searchTags}
                onChange={pool.setSearchTags}
                searchValue={pool.searchQuery}
                onSearch={pool.setSearchQuery}
                open={pool.filterOpen}
                onDropdownVisibleChange={pool.setFilterOpen}
                allowClear
                maxTagCount="responsive"
                suffixIcon={<SearchOutlined />}
                notFoundContent={<></>}
                dropdownStyle={
                  pool.allTags.length === 0
                    ? {
                        padding: 0,
                        border: "none",
                        boxShadow: "none",
                        height: 0,
                        overflow: "hidden",
                      }
                    : undefined
                }
                dropdownRender={() =>
                  pool.allTags.length > 0 ? (
                    <SkillFilterDropdown
                      allTags={pool.allTags}
                      searchTags={pool.searchTags}
                      setSearchTags={pool.setSearchTags}
                      styles={styles}
                    />
                  ) : (
                    <div />
                  )
                }
              />
            </div>
            <div className={styles.toolbarRight}>
              <div className={styles.viewToggle}>
                <button
                  className={`${styles.viewToggleBtn} ${
                    pool.viewMode === "list" ? styles.viewToggleBtnActive : ""
                  }`}
                  onClick={() => pool.setViewMode("list")}
                  title={t("skills.listView")}
                >
                  <UnorderedListOutlined />
                </button>
                <button
                  className={`${styles.viewToggleBtn} ${
                    pool.viewMode === "card" ? styles.viewToggleBtnActive : ""
                  }`}
                  onClick={() => pool.setViewMode("card")}
                  title={t("skills.gridView")}
                >
                  <AppstoreOutlined />
                </button>
              </div>
            </div>
          </div>
        )}

        {pool.loading ? (
          <div className={styles.loading}>
            <span className={styles.loadingText}>{t("common.loading")}</span>
          </div>
        ) : pool.viewMode === "card" ? (
          <div className={styles.skillsGrid}>
            {visibleSkills.map((skill: PoolSkillSpec) => (
              <PoolSkillCard
                key={skill.name}
                skill={skill}
                isSelected={pool.selectedPoolSkills.has(skill.name)}
                batchModeEnabled={pool.batchModeEnabled}
                onToggleSelect={pool.togglePoolSelect}
                onEdit={pool.openEdit}
                onBroadcast={pool.openBroadcast}
                onDelete={pool.handleDelete}
              />
            ))}
            {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
          </div>
        ) : (
          <div className={styles.skillsList}>
            {visibleSkills.map((skill: PoolSkillSpec) => (
              <PoolSkillListItem
                key={skill.name}
                skill={skill}
                isSelected={pool.selectedPoolSkills.has(skill.name)}
                batchModeEnabled={pool.batchModeEnabled}
                onToggleSelect={pool.togglePoolSelect}
                onEdit={pool.openEdit}
                onBroadcast={pool.openBroadcast}
                onDelete={pool.handleDelete}
              />
            ))}
            {hasMore && <div ref={sentinelRef} style={{ height: 1 }} />}
          </div>
        )}
      </div>

      <ImportHubModal
        open={pool.importModalOpen}
        importing={pool.importing}
        onCancel={pool.closeImportModal}
        onConfirm={pool.handleConfirmImport}
        hint={t("skillPool.externalHubHint")}
      />

      <BroadcastModal
        open={pool.mode === "broadcast"}
        skills={pool.skills}
        workspaces={pool.workspaces}
        initialSkillNames={pool.broadcastInitialNames}
        onCancel={pool.closeModal}
        onConfirm={pool.handleBroadcast}
      />

      <ImportBuiltinModal
        open={pool.importBuiltinModalOpen}
        loading={pool.importBuiltinLoading}
        sources={pool.builtinSources}
        notice={pool.builtinNotice}
        defaultLanguage={pool.builtinLanguage}
        defaultSelectedNames={pool.builtinNotice?.actionable_skill_names}
        onCancel={pool.closeImportBuiltin}
        onConfirm={pool.handleImportBuiltins}
      />

      <PoolSkillDrawer
        mode={pool.mode}
        activeSkill={pool.activeSkill}
        form={pool.form}
        drawerContent={pool.drawerContent}
        showMarkdown={pool.showMarkdown}
        configText={pool.configText}
        availableTags={pool.allTags}
        onClose={pool.closeDrawer}
        onSave={pool.handleSavePoolSkill}
        onContentChange={pool.handleDrawerContentChange}
        onShowMarkdownChange={pool.setShowMarkdown}
        onConfigTextChange={pool.setConfigText}
        onChangeBuiltinLanguage={pool.handleBuiltinLanguageSwitch}
        validateFrontmatter={pool.validateFrontmatter}
      />

      {pool.conflictRenameModal}
    </div>
  );
}

export default SkillPoolPage;
