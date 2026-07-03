import { Button, Input, Select, Tooltip } from "@agentscope-ai/design";
import { Badge } from "antd";
import {
  AppstoreOutlined,
  ArrowLeftOutlined,
  CloseOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SendOutlined,
  SyncOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { ImportHubModal } from "../../Agent/Skills/components/ImportHubModal";
import { SkillFilterDropdown } from "../../Agent/Skills/components/SkillFilterDropdown";
import { AddSkillDropdown } from "../../Agent/Skills/components/AddSkillDropdown";
import { MarketPanel } from "../Market/MarketPanel";
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

  const [searchParams, setSearchParams] = useSearchParams();
  const marketView = searchParams.get("view") === "market";

  const openMarket = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("view", "market");
      return next;
    });
  }, [setSearchParams]);

  const closeMarket = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("view");
      return next;
    });
  }, [setSearchParams]);

  if (marketView) {
    return (
      <div className={styles.skillsPage}>
        <PageHeader
          items={[
            { title: t("nav.settings") },
            { title: t("nav.skillPool") },
            { title: t("nav.market") },
          ]}
          extra={
            <Button icon={<ArrowLeftOutlined />} onClick={closeMarket}>
              {t("common.back")}
            </Button>
          }
        />
        <MarketPanel installTarget="pool" />
      </div>
    );
  }

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
                  <Button type="primary" onClick={pool.toggleBatchMode}>
                    {t("skills.batchOperation")}
                  </Button>
                  <AddSkillDropdown
                    onCreate={pool.openCreate}
                    onUploadZip={() => pool.zipInputRef.current?.click()}
                    onFromUrl={() => pool.setImportModalOpen(true)}
                    onBrowseMarket={openMarket}
                  />
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
              <Input
                className={styles.searchInput}
                placeholder={t("skills.searchPlaceholder")}
                value={pool.searchQuery}
                onChange={(e) => pool.setSearchQuery(e.target.value)}
                allowClear
              />
              <Select
                mode="multiple"
                className={styles.tagSelect}
                placeholder={t("skills.filterByTag")}
                value={pool.searchTags}
                onChange={pool.setSearchTags}
                open={pool.filterOpen}
                onOpenChange={pool.setFilterOpen}
                allowClear
                maxTagCount="responsive"
                notFoundContent={<></>}
                popupRender={() =>
                  pool.allTags.length > 0 ? (
                    <SkillFilterDropdown
                      allTags={pool.allTags}
                      searchTags={pool.searchTags}
                      setSearchTags={pool.setSearchTags}
                      styles={styles}
                    />
                  ) : (
                    <div className={styles.tagSelectEmpty}>
                      {t("skills.noTags")}
                    </div>
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
        ) : pool.sortedSkills.length === 0 && pool.skills.length > 0 ? (
          <div className={styles.noSearchResults}>
            <span className={styles.noSearchResultsIcon}>🔍</span>
            <span className={styles.noSearchResultsText}>
              {t("skills.noSearchResults")}
            </span>
          </div>
        ) : pool.viewMode === "card" ? (
          <div className={`${styles.skillsGrid} responsive-grid`}>
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
                onToggleAutoUpdate={pool.handleToggleAutoUpdate}
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
        workspaces={pool.workspaces}
        autoUpdateEnabled={pool.autoUpdateEnabled}
        autoUpdateTargets={pool.autoUpdateTargets}
        onClose={pool.closeDrawer}
        onSave={pool.handleSavePoolSkill}
        onContentChange={pool.handleDrawerContentChange}
        onShowMarkdownChange={pool.setShowMarkdown}
        onConfigTextChange={pool.setConfigText}
        onChangeBuiltinLanguage={pool.handleBuiltinLanguageSwitch}
        onAutoUpdateEnabledChange={pool.setAutoUpdateEnabled}
        onAutoUpdateTargetsChange={pool.setAutoUpdateTargets}
        validateFrontmatter={pool.validateFrontmatter}
      />

      {pool.conflictRenameModal}
    </div>
  );
}

export default SkillPoolPage;
