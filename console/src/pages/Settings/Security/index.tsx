import { Button, Tabs } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useSecurityPage } from "./useSecurityPage";
import {
  ToolGuardTab,
  RuleModal,
  PreviewModal,
  SkillScannerSection,
  FileGuardSection,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

function SecurityPage() {
  const { t } = useTranslation();

  const {
    activeTab,
    setActiveTab,
    form,
    config,
    enabled,
    setEnabled,
    toolOptions,
    saving,
    handleSave,
    handleReset,
    mergedRules,
    builtinRules,
    customRules,
    toggleRule,
    deleteCustomRule,
    openAddRule,
    openEditRule,
    shellEvasionChecks,
    toggleShellEvasionCheck,
    editModal,
    setEditModal,
    editingRule,
    editForm,
    handleEditSave,
    previewRule,
    setPreviewRule,
    fileGuardHandlers,
    onFileGuardHandlersReady,
    loading,
    error,
    fetchAll,
  } = useSecurityPage();

  // Loading state
  if (loading) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchAll} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.securityPage}>
      <PageHeader
        parent={t("security.parent")}
        current={t("security.security")}
      />

      <div className={styles.content}>
        <Tabs
          className={styles.mainTabs}
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "toolGuard",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.toolGuardTitle")}
                </span>
              ),
              children: (
                <ToolGuardTab
                  form={form}
                  config={config}
                  enabled={enabled}
                  setEnabled={setEnabled}
                  toolOptions={toolOptions}
                  mergedRules={mergedRules}
                  toggleRule={toggleRule}
                  onPreviewRule={setPreviewRule}
                  onEditRule={openEditRule}
                  onDeleteRule={deleteCustomRule}
                  openAddRule={openAddRule}
                  shellEvasionChecks={shellEvasionChecks}
                  toggleShellEvasionCheck={toggleShellEvasionCheck}
                />
              ),
            },
            {
              key: "fileGuard",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.fileGuard.title")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionFileGuardContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.fileGuard.description")}
                    </p>
                    <FileGuardSection onSave={onFileGuardHandlersReady} />
                  </div>
                </div>
              ),
            },
            {
              key: "skillScanner",
              label: (
                <span className={styles.tabLabel}>
                  {t("security.skillScanner.title")}
                </span>
              ),
              children: (
                <div className={styles.tabContent}>
                  <div className={styles.sectionSkillScannerContainer}>
                    <p className={styles.tabDescription}>
                      {t("security.skillScanner.description")}
                    </p>
                    <SkillScannerSection />
                  </div>
                </div>
              ),
            },
          ]}
        />
      </div>

      {activeTab === "toolGuard" && (
        <div className={styles.footerButtons}>
          <Button
            onClick={handleReset}
            disabled={saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button type="primary" onClick={handleSave} loading={saving}>
            {t("common.save")}
          </Button>
        </div>
      )}

      {activeTab === "fileGuard" && fileGuardHandlers && (
        <div className={styles.footerButtons}>
          <Button
            onClick={fileGuardHandlers.reset}
            disabled={fileGuardHandlers.saving}
            style={{ marginRight: 8 }}
          >
            {t("common.reset")}
          </Button>
          <Button
            type="primary"
            onClick={fileGuardHandlers.save}
            loading={fileGuardHandlers.saving}
          >
            {t("common.save")}
          </Button>
        </div>
      )}

      <RuleModal
        open={editModal}
        editingRule={editingRule}
        existingRuleIds={[
          ...builtinRules.map((r) => r.id),
          ...customRules.map((r) => r.id),
        ]}
        onOk={handleEditSave}
        onCancel={() => setEditModal(false)}
        form={editForm}
      />

      <PreviewModal rule={previewRule} onClose={() => setPreviewRule(null)} />
    </div>
  );
}

export default SecurityPage;
