import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslation } from "react-i18next";
import { useSecurityPage } from "./useSecurityPage";
import {
  ToolGuardTab,
  RuleModal,
  PreviewModal,
  SkillScannerSection,
  FileGuardSection,
  AllowNoAuthHostsTab,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

function SecurityPage() {
  const { t } = useTranslation();

  const {
    activeTab,
    setActiveTab,
    formEnabled,
    setFormEnabled,
    formGuardedTools,
    setFormGuardedTools,
    formDeniedTools,
    setFormDeniedTools,
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
    toggleAutoDeny,
    deleteCustomRule,
    openAddRule,
    openEditRule,
    shellEvasionChecks,
    toggleShellEvasionCheck,
    editModal,
    setEditModal,
    editingRule,
    handleEditSave,
    previewRule,
    setPreviewRule,
    fileGuardHandlers,
    onFileGuardHandlersReady,
    allowNoAuthHostsHandlers,
    onAllowNoAuthHostsHandlersReady,
    loading,
    error,
    fetchAll,
  } = useSecurityPage();

  if (loading) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.securityPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="sm" onClick={fetchAll} className="mt-3">
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
          value={activeTab}
          onValueChange={setActiveTab}
          className={styles.mainTabs}
        >
          <TabsList>
            <TabsTrigger value="toolGuard">
              <span className={styles.tabLabel}>
                {t("security.toolGuardTitle")}
              </span>
            </TabsTrigger>
            <TabsTrigger value="fileGuard">
              <span className={styles.tabLabel}>
                {t("security.fileGuard.title")}
              </span>
            </TabsTrigger>
            <TabsTrigger value="skillScanner">
              <span className={styles.tabLabel}>
                {t("security.skillScanner.title")}
              </span>
            </TabsTrigger>
            <TabsTrigger value="allowNoAuthHosts">
              <span className={styles.tabLabel}>
                {t("security.allowNoAuthHosts.title")}
              </span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="toolGuard">
            <ToolGuardTab
              config={config}
              enabled={enabled}
              setEnabled={setEnabled}
              formEnabled={formEnabled}
              setFormEnabled={setFormEnabled}
              formGuardedTools={formGuardedTools}
              setFormGuardedTools={setFormGuardedTools}
              formDeniedTools={formDeniedTools}
              setFormDeniedTools={setFormDeniedTools}
              toolOptions={toolOptions}
              mergedRules={mergedRules}
              toggleRule={toggleRule}
              toggleAutoDeny={toggleAutoDeny}
              onPreviewRule={setPreviewRule}
              onEditRule={openEditRule}
              onDeleteRule={deleteCustomRule}
              openAddRule={openAddRule}
              shellEvasionChecks={shellEvasionChecks}
              toggleShellEvasionCheck={toggleShellEvasionCheck}
            />
          </TabsContent>

          <TabsContent value="fileGuard">
            <div className={styles.tabContent}>
              <div className={styles.sectionFileGuardContainer}>
                <p className={styles.tabDescription}>
                  {t("security.fileGuard.description")}
                </p>
                <FileGuardSection onSave={onFileGuardHandlersReady} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="skillScanner">
            <div className={styles.tabContent}>
              <div className={styles.sectionSkillScannerContainer}>
                <p className={styles.tabDescription}>
                  {t("security.skillScanner.description")}
                </p>
                <SkillScannerSection />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="allowNoAuthHosts">
            <AllowNoAuthHostsTab onSave={onAllowNoAuthHostsHandlersReady} />
          </TabsContent>
        </Tabs>
      </div>

      {activeTab === "toolGuard" && (
        <div className={styles.footerButtons}>
          <Button
            variant="outline"
            onClick={handleReset}
            disabled={saving}
            className="mr-2"
          >
            {t("common.reset")}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      )}

      {activeTab === "fileGuard" && fileGuardHandlers && (
        <div className={styles.footerButtons}>
          <Button
            variant="outline"
            onClick={fileGuardHandlers.reset}
            disabled={fileGuardHandlers.saving}
            className="mr-2"
          >
            {t("common.reset")}
          </Button>
          <Button
            onClick={() => void fileGuardHandlers.save()}
            disabled={fileGuardHandlers.saving}
          >
            {fileGuardHandlers.saving ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      )}

      {activeTab === "allowNoAuthHosts" && allowNoAuthHostsHandlers && (
        <div className={styles.footerButtons}>
          <Button
            variant="outline"
            onClick={allowNoAuthHostsHandlers.reset}
            disabled={allowNoAuthHostsHandlers.saving}
            className="mr-2"
          >
            {t("common.reset")}
          </Button>
          <Button
            onClick={() => void allowNoAuthHostsHandlers.save()}
            disabled={allowNoAuthHostsHandlers.saving}
          >
            {allowNoAuthHostsHandlers.saving
              ? t("common.saving")
              : t("common.save")}
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
      />

      <PreviewModal rule={previewRule} onClose={() => setPreviewRule(null)} />
    </div>
  );
}

export default SecurityPage;
