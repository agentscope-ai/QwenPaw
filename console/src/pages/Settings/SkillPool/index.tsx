import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  LayoutGrid,
  X,
  Trash2,
  Import,
  Plus,
  RefreshCw,
  Send,
  RefreshCcw,
  Upload,
  List,
} from "lucide-react";
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
                <Button
                  variant="outline"
                  size="sm"
                  onClick={pool.selectAllPool}
                >
                  {t("skills.selectAll")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={pool.clearPoolSelection}
                >
                  <X size={14} className="mr-1" />
                  {t("skills.clearSelection")}
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => void pool.handleBatchDeletePool()}
                >
                  <Trash2 size={14} className="mr-1" />
                  {t("common.delete")} ({pool.selectedPoolSkills.size})
                </Button>
                <Button size="sm" onClick={pool.toggleBatchMode}>
                  {t("skills.exitBatch")}
                </Button>
              </div>
            ) : (
              <>
                <div className={styles.headerActionsLeft}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void pool.handleRefresh()}
                        disabled={pool.loading}
                      >
                        <RefreshCw
                          size={14}
                          className={pool.loading ? "animate-spin" : ""}
                        />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("skillPool.refreshHint")}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        className={styles.primaryTransferButton}
                        onClick={() => pool.openBroadcast()}
                      >
                        <Send size={14} className="mr-1" />
                        {t("skillPool.broadcast")}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("skillPool.broadcastHint")}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="relative">
                        {pool.hasUnseenBuiltinNotice && (
                          <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-primary" />
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void pool.openImportBuiltin()}
                        >
                          <RefreshCcw size={14} className="mr-1" />
                          {t("skillPool.importBuiltin")}
                        </Button>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      {pool.hasUnseenBuiltinNotice
                        ? builtinNoticeLines.length > 0
                          ? builtinNoticeLines.map((line) => (
                              <div key={line}>{line}</div>
                            ))
                          : t("skillPool.importBuiltinAlertHint", {
                              count: pool.builtinNoticeTotal,
                            })
                        : t("skillPool.importBuiltinHint")}
                    </TooltipContent>
                  </Tooltip>
                </div>
                <div className={styles.headerActionsRight}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => pool.zipInputRef.current?.click()}
                      >
                        <Upload size={14} className="mr-1" />
                        {t("skills.uploadZip")}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("skillPool.uploadZipHint")}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => pool.setImportModalOpen(true)}
                      >
                        <Import size={14} className="mr-1" />
                        {t("skills.importHub")}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("skillPool.importHubHint")}
                    </TooltipContent>
                  </Tooltip>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={pool.toggleBatchMode}
                  >
                    {t("skills.batchOperation")}
                  </Button>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        size="sm"
                        className={styles.primaryActionButton}
                        onClick={pool.openCreate}
                      >
                        <Plus size={14} className="mr-1" />
                        {t("skills.createSkill")}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("skills.createSkillHint")}
                    </TooltipContent>
                  </Tooltip>
                </div>
              </>
            )}
          </div>
        }
      />

      <div className={styles.content}>
        {!pool.loading && pool.skills.length > 0 && (
          <div className={styles.toolbar}>
            <div className={styles.searchContainer}>
              <Input
                className={styles.searchInput}
                placeholder={t("skills.searchPlaceholder")}
                value={pool.searchQuery}
                onChange={(e) => pool.setSearchQuery(e.target.value)}
              />
              {pool.allTags.length > 0 && (
                <div className="relative">
                  <button
                    className={`${styles.tagSelect} border rounded-md px-2 py-1 text-sm`}
                    onClick={() => pool.setFilterOpen((v) => !v)}
                  >
                    {pool.searchTags.length > 0
                      ? pool.searchTags.join(", ")
                      : t("skills.filterByTag")}
                  </button>
                  {pool.filterOpen && (
                    <div className="absolute z-50 bg-popover border rounded-md shadow-md mt-1 min-w-[200px]">
                      <SkillFilterDropdown
                        allTags={pool.allTags}
                        searchTags={pool.searchTags}
                        setSearchTags={pool.setSearchTags}
                        styles={styles}
                      />
                    </div>
                  )}
                </div>
              )}
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
                  <List size={16} />
                </button>
                <button
                  className={`${styles.viewToggleBtn} ${
                    pool.viewMode === "card" ? styles.viewToggleBtnActive : ""
                  }`}
                  onClick={() => pool.setViewMode("card")}
                  title={t("skills.gridView")}
                >
                  <LayoutGrid size={16} />
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
        onSave={() => void pool.handleSavePoolSkill()}
        onContentChange={pool.handleDrawerContentChange}
        onShowMarkdownChange={pool.setShowMarkdown}
        onConfigTextChange={pool.setConfigText}
        onChangeBuiltinLanguage={pool.handleBuiltinLanguageSwitch}
        validateFrontmatter={pool.validateFrontmatter}
      />

      {pool.conflictRenameModal}

      {/* Generic confirm dialog (replaces Modal.confirm) */}
      <AlertDialog
        open={pool.confirmDialog.open}
        onOpenChange={(v) => {
          if (!v) pool.handleConfirmDialogCancel();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{pool.confirmDialog.title}</AlertDialogTitle>
            {pool.confirmDialog.content && (
              <AlertDialogDescription asChild>
                <div>{pool.confirmDialog.content}</div>
              </AlertDialogDescription>
            )}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={pool.handleConfirmDialogCancel}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction onClick={pool.handleConfirmDialogOk}>
              {t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default SkillPoolPage;
