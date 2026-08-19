import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { ArrowLeftOutlined, PlusOutlined } from "@ant-design/icons";
import { Button } from "@agentscope-ai/design";
import { MarketPanel } from "../../Settings/Market/MarketPanel";
import {
  SkillCard,
  SkillDrawer,
  PoolTransferModal,
  ImportHubModal,
  HeaderActions,
  SkillsToolbar,
  SkillListItem,
  ProviderSkillDrawer,
  getSkillVisual,
} from "./components";
import type { SkillSpec } from "../../../api/types";
import type { HarnessDiscoveredSkill } from "../../../api/modules/harness";
import { PageHeader } from "@/components/PageHeader";
import { useSkillsPage } from "./useSkillsPage";
import styles from "./index.module.less";
import { useMemo, useCallback, useState } from "react";
import { LockKeyhole, Sparkles } from "lucide-react";

function SkillsPage() {
  const { t } = useTranslation();
  const {
    skills,
    providerSkills,
    visibleSkills,
    hasMore,
    sentinelRef,
    poolSkills,
    allTags,
    sortedSkills,
    conflictRenameModal,
    loading,
    uploading,
    importing,
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
    selectAll,
    clearSelection,
    toggleBatchMode,
    toggleEnabled,
    refreshSkills,
    hardRefresh,
    cancelImport,
  } = useSkillsPage();

  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedProviderSkill, setSelectedProviderSkill] =
    useState<HarnessDiscoveredSkill | null>(null);
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

  const handleMarketInstalled = useCallback(() => {
    void refreshSkills();
  }, [refreshSkills]);

  // Split skills into enabled and disabled groups
  const { enabledSkills, disabledSkills } = useMemo(() => {
    const enabled = visibleSkills.filter((skill) => skill.enabled);
    const disabled = visibleSkills.filter((skill) => !skill.enabled);
    return { enabledSkills: enabled, disabledSkills: disabled };
  }, [visibleSkills]);
  const enabledSkillCount = useMemo(
    () => sortedSkills.filter((skill) => skill.enabled).length,
    [sortedSkills],
  );

  // Shared renderer for SkillListItem (used by both enabled and disabled sections)
  const renderSkillListItem = useCallback(
    (skill: SkillSpec) => (
      <SkillListItem
        key={skill.name}
        skill={skill}
        batchModeEnabled={batchModeEnabled}
        isSelected={selectedSkills.has(skill.name)}
        onSelect={() => toggleSelect(skill.name)}
        onClick={() => handleEdit(skill)}
        onToggleEnabled={async () => {
          await toggleEnabled(skill);
          await refreshSkills();
        }}
        onDelete={() => handleDelete(skill)}
      />
    ),
    [
      batchModeEnabled,
      selectedSkills,
      toggleSelect,
      handleEdit,
      toggleEnabled,
      refreshSkills,
      handleDelete,
    ],
  );

  if (marketView) {
    return (
      <div className={styles.skillsPage}>
        <PageHeader
          items={[
            { title: t("nav.agent") },
            { title: t("skills.title") },
            { title: t("nav.market") },
          ]}
          extra={
            <Button icon={<ArrowLeftOutlined />} onClick={closeMarket}>
              {t("common.back")}
            </Button>
          }
        />
        <MarketPanel
          installTarget="workspace"
          onInstalled={handleMarketInstalled}
        />
      </div>
    );
  }

  return (
    <div className={styles.skillsPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("skills.title") }]}
        extra={
          <HeaderActions
            batchModeEnabled={batchModeEnabled}
            selectedSkills={selectedSkills}
            loading={loading}
            uploading={uploading}
            fileInputRef={fileInputRef}
            onSelectAll={selectAll}
            onClearSelection={clearSelection}
            onUploadToPool={handleUploadToPool}
            onBatchEnable={handleBatchEnable}
            onBatchDisable={handleBatchDisable}
            onBatchDelete={handleBatchDelete}
            onToggleBatchMode={toggleBatchMode}
            onHardRefresh={hardRefresh}
            onOpenDownloadPool={() => setPoolModal("download")}
            onOpenUploadPool={() => setPoolModal("upload")}
            onUploadClick={handleUploadClick}
            onImportHub={() => setImportModalOpen(true)}
            onCreate={handleCreate}
            onBrowseMarket={openMarket}
            onFileChange={handleFileChange}
          />
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

      {providerSkills.length > 0 && (
        <div className={styles.managementBanner}>
          <Sparkles size={16} />
          <div>
            <strong>{t("skills.qwenpawManaged")}</strong>
            <span>{t("skills.qwenpawManagedHint")}</span>
          </div>
        </div>
      )}

      {!loading && skills.length > 0 && (
        <SkillsToolbar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          searchTags={searchTags}
          onTagsChange={setSearchTags}
          allTags={allTags}
          filterOpen={filterOpen}
          onFilterOpenChange={setFilterOpen}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
        />
      )}

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : skills.length === 0 ? (
        <div
          className={`${styles.emptyState} ${
            providerSkills.length > 0 ? styles.emptyStateCompact : ""
          }`}
        >
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
      ) : sortedSkills.length === 0 ? (
        <div className={styles.noSearchResults}>
          <span className={styles.noSearchResultsIcon}>🔍</span>
          <span className={styles.noSearchResultsText}>
            {t("skills.noSearchResults")}
          </span>
        </div>
      ) : (
        <>
          {/* Enabled Skills Section */}
          {enabledSkills.length > 0 && (
            <div className={styles.panelSection}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGreen} />
                {t("skills.enabledSkills")}
                <span className={styles.panelCount}>
                  {enabledSkillCount} {t("skills.active")}
                </span>
              </div>

              {viewMode === "card" ? (
                <div className={styles.skillsGrid}>
                  {enabledSkills.map((skill) => (
                    <SkillCard
                      key={skill.name}
                      skill={skill}
                      selected={
                        batchModeEnabled
                          ? selectedSkills.has(skill.name)
                          : undefined
                      }
                      onSelect={() => toggleSelect(skill.name)}
                      onClick={() => handleEdit(skill)}
                      onMouseEnter={() => {}}
                      onMouseLeave={() => {}}
                      onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
                      onDelete={(e) => handleDelete(skill, e)}
                    />
                  ))}
                </div>
              ) : (
                <div className={styles.skillsList}>
                  {enabledSkills.map(renderSkillListItem)}
                </div>
              )}
            </div>
          )}

          {/* Disabled Skills Section */}
          {disabledSkills.length > 0 && (
            <div className={styles.panelSectionDashed}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGray} />
                {t("skills.disabledSkills")}
              </div>
              {viewMode === "card" ? (
                <div className={styles.disabledSkillsGrid}>
                  {disabledSkills.map((skill) => (
                    <div
                      key={skill.name}
                      className={styles.disabledSkillGridItem}
                      onClick={() => handleEdit(skill)}
                    >
                      <span className={styles.disabledSkillGridIcon}>
                        {getSkillVisual(skill.name, skill.emoji)}
                      </span>
                      <span className={styles.disabledSkillGridName}>
                        {skill.name}
                      </span>
                      <span
                        className={styles.disabledSkillGridAction}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleToggleEnabled(skill, e);
                        }}
                      >
                        {t("common.enable")}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={styles.skillsList}>
                  {disabledSkills.map(renderSkillListItem)}
                </div>
              )}
            </div>
          )}

          {hasMore && (
            <div
              ref={sentinelRef}
              style={{ height: 1, minHeight: 1, flexShrink: 0 }}
            />
          )}
        </>
      )}

      {providerSkills.length > 0 && (
        <section className={styles.providerSkillsSection}>
          <div className={styles.providerSkillsHeading}>
            <div>
              <span className={styles.providerSkillsTitle}>
                <LockKeyhole size={16} />
                {t("skills.providerManaged")}
              </span>
              <p>{t("skills.providerManagedHint")}</p>
            </div>
            <span className={styles.providerSkillsCount}>
              {providerSkills.length}
            </span>
          </div>
          <div className={styles.providerSkillsGrid}>
            {providerSkills.map((skill) => (
              <button
                type="button"
                key={`${skill.provider_id}:${skill.source}:${skill.name}`}
                className={styles.providerSkillCard}
                onClick={() => setSelectedProviderSkill(skill)}
                aria-label={`${t("common.view")}: ${skill.name}`}
              >
                <div className={styles.providerSkillTop}>
                  <span className={styles.providerSkillIcon}>
                    <LockKeyhole size={15} />
                  </span>
                  <span
                    className={
                      skill.enabled
                        ? styles.providerSkillEnabled
                        : styles.providerSkillDisabled
                    }
                  >
                    {skill.enabled ? t("common.enabled") : t("common.disabled")}
                  </span>
                </div>
                <strong title={skill.name}>{skill.name}</strong>
                <p>{skill.description || t("skills.noDescription")}</p>
                <div className={styles.providerSkillMeta}>
                  <span>{skill.provider_id}</span>
                  {skill.source && <span>{skill.source}</span>}
                  <span>{t("skills.providerOnly")}</span>
                  <span>{t("skills.readOnly")}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      <ProviderSkillDrawer
        open={selectedProviderSkill !== null}
        skill={selectedProviderSkill}
        onClose={() => setSelectedProviderSkill(null)}
      />

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
        editing={drawerLoading || editingSkill !== null}
        editingName={editingSkillName}
        loading={drawerLoading}
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
