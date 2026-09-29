import { Search } from "lucide-react";
import { Button, Tooltip } from "@agentscope-ai/design";
import { Badge } from "antd";
import {
  X as CloseOutlined,
  Trash2 as DeleteOutlined,
  RefreshCw as ReloadOutlined,
  Send as SendOutlined,
  RefreshCw as SyncOutlined,
} from "lucide-react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { useId, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ImportHubModal } from "../../Agent/Skills/components/ImportHubModal";
import { SkillsToolbar } from "../../Agent/Skills/components/SkillsToolbar";
import { AddSkillDropdown } from "../../Agent/Skills/components/AddSkillDropdown";
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
  const transferId = useId();
  const reduced = useReducedMotion();
  const builtinNoticeLines = getBuiltinNoticeLines(pool.builtinNotice, t);
  const {
    visibleItems: visibleSkills,
    hasMore,
    sentinelRef,
  } = useProgressiveRender(pool.sortedSkills);

  const navigate = useNavigate();

  const openMarket = useCallback(() => {
    navigate("/market?tab=skills&target=pool");
  }, [navigate]);

  return (
    <LayoutGroup id={transferId}>
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
                    icon={<CloseOutlined size="1em" />}
                  >
                    {t("skills.clearSelection")}
                  </Button>
                  <Button
                    type="default"
                    className={styles.primaryTransferButton}
                    icon={<SendOutlined size="1em" />}
                    disabled={pool.selectedPoolSkills.size === 0}
                    onClick={pool.openBatchBroadcast}
                  >
                    {t("skillPool.broadcast")} ({pool.selectedPoolSkills.size})
                  </Button>
                  <Button
                    danger
                    icon={<DeleteOutlined size="1em" />}
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
                        icon={
                          <ReloadOutlined
                            size="1em"
                            data-spinning={pool.loading}
                          />
                        }
                        onClick={pool.handleRefresh}
                        disabled={pool.loading}
                      />
                    </Tooltip>
                    <motion.div
                      layoutId={reduced ? undefined : transferId}
                      style={{ borderRadius: 20 }}
                      whileTap={reduced ? undefined : { scale: 0.96 }}
                    >
                      <Tooltip title={t("skillPool.broadcastHint")}>
                        <Button
                          type="default"
                          className={styles.primaryTransferButton}
                          icon={<SendOutlined size="1em" />}
                          onClick={() => pool.openBroadcast()}
                        >
                          {t("skillPool.broadcast")}
                        </Button>
                      </Tooltip>
                    </motion.div>
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
                          icon={<SyncOutlined size="1em" />}
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
            <SkillsToolbar
              searchQuery={pool.searchQuery}
              onSearchChange={pool.setSearchQuery}
              searchTags={pool.searchTags}
              onTagsChange={pool.setSearchTags}
              allTags={pool.allTags}
              filterOpen={pool.filterOpen}
              onFilterOpenChange={pool.setFilterOpen}
              viewMode={pool.viewMode}
              onViewModeChange={pool.setViewMode}
            />
          )}

          {pool.loading ? (
            <div className={styles.loading}>
              <span className={styles.loadingText}>{t("common.loading")}</span>
            </div>
          ) : pool.sortedSkills.length === 0 && pool.skills.length > 0 ? (
            <div className={styles.noSearchResults}>
              <span className={styles.noSearchResultsIcon}>
                <Search size={28} aria-hidden="true" />
              </span>
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
                  automationPending={pool.automationPendingSkills.has(
                    skill.name,
                  )}
                  onToggleSelect={pool.togglePoolSelect}
                  onEdit={pool.openEdit}
                  onBroadcast={pool.openBroadcast}
                  onDelete={pool.handleDelete}
                  onAutomationQuickAction={pool.handleAutomationQuickAction}
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
          surfaceId={transferId}
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
          loading={pool.detailLoading}
          saving={pool.saving}
          skillName={pool.detailSkillName}
          form={pool.form}
          drawerContent={pool.drawerContent}
          showMarkdown={pool.showMarkdown}
          configText={pool.configText}
          availableTags={pool.allTags}
          workspaces={pool.workspaces}
          builtinAutoUpdateEnabled={pool.builtinAutoUpdateEnabled}
          autoSyncEnabled={pool.autoSyncEnabled}
          autoSyncTargets={pool.autoSyncTargets}
          onClose={pool.closeDrawer}
          onSave={pool.handleSavePoolSkill}
          onContentChange={pool.handleDrawerContentChange}
          onShowMarkdownChange={pool.setShowMarkdown}
          onConfigTextChange={pool.setConfigText}
          onChangeBuiltinLanguage={pool.handleBuiltinLanguageSwitch}
          onBuiltinAutoUpdateEnabledChange={pool.setBuiltinAutoUpdateEnabled}
          onAutoSyncEnabledChange={pool.setAutoSyncEnabled}
          onAutoSyncTargetsChange={pool.setAutoSyncTargets}
          validateFrontmatter={pool.validateFrontmatter}
        />

        {pool.conflictRenameModal}
      </div>
    </LayoutGroup>
  );
}

export default SkillPoolPage;
