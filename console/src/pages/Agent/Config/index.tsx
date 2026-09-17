import { useState, useMemo, useEffect, useCallback } from "react";
import { Button, Form, Tabs } from "@agentscope-ai/design";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useAgentConfig } from "./useAgentConfig.tsx";
import { modelCatalogApi } from "@/api/modules/modelCatalog";
import {
  ReactAgentCard,
  LlmRetryCard,
  LlmRateLimiterCard,
  ToolExecutionLevelCard,
  AgentLoopCard,
  EmbeddingModelCard,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
} from "@/constants/backendMappings";
import { useAgentStore } from "@/stores/agentStore";
import styles from "./index.module.less";
import { MemoryMaintenanceContext } from "./memoryMaintenanceContext";
import { useReMeRuntimeStatus } from "./useReMeRuntimeStatus";
import { ReadOnlyConfigSummary } from "./ReadOnlyConfigSummary";
import { GovernanceConfigAlert } from "./GovernanceConfigAlert";
import type { AgentRequestContext } from "@/api/modules/agentRequestContext";

function AgentConfigPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const governanceAgentId =
    searchParams.get("governance") === "runtime-config"
      ? searchParams.get("agentId") || undefined
      : undefined;
  const requestContext: AgentRequestContext | undefined = useMemo(
    () =>
      governanceAgentId
        ? { agentId: governanceAgentId, governance: true }
        : undefined,
    [governanceAgentId],
  );
  const [activeTab, setActiveTab] = useState(
    searchParams.get("tab") || "reactAgent",
  );
  const [needsReindex, setNeedsReindex] = useState(false);
  const [localReindexing, setLocalReindexing] = useState(false);
  const [configRevision, setConfigRevision] = useState(0);
  const syncReindexRequirement = useCallback(
    (config: { reme_light_memory_config?: { needs_reindex?: boolean } }) => {
      setNeedsReindex(config.reme_light_memory_config?.needs_reindex === true);
      setConfigRevision((revision) => revision + 1);
    },
    [],
  );
  const {
    form,
    loading,
    saving,
    error,
    language,
    savingLang,
    timezone,
    savingTimezone,
    access,
    readOnlySummary,
    isReadOnly,
    approvalLevel,
    setApprovalLevel,
    fetchConfig,
    handleSave,
    runtimeState,
    retryReloading,
    handleRetryReload,
    handleLanguageChange,
    handleTimezoneChange,
  } = useAgentConfig(syncReindexRequirement, governanceAgentId);

  const llmRetryEnabled = Form.useWatch("llm_retry_enabled", form) ?? true;
  const contextBackend =
    Form.useWatch("context_manager_backend", form) || "light";
  const memoryBackend =
    Form.useWatch("memory_manager_backend", form) || "remelight";
  const { selectedAgent } = useAgentStore();
  const canEdit = access?.can_edit === true;
  const { runtimeStatus, checkMemoryStatus } = useReMeRuntimeStatus(
    canEdit && memoryBackend === "remelight",
    requestContext,
  );
  const remoteReindexing =
    runtimeStatus.type === "healthy" && runtimeStatus.data.runtime.reindexing;
  const reindexing = localReindexing || remoteReindexing;

  const [maxInputLength, setMaxInputLength] = useState(131072);
  const refreshEffectiveContextWindow = useCallback(() => {
    if (!canEdit) return Promise.resolve();
    return modelCatalogApi
      .default(selectedAgent || undefined)
      .then((info) => {
        if (info.effective_max_input_length != null) {
          setMaxInputLength(info.effective_max_input_length);
          return;
        }
        if (info.active_llm) {
          return modelCatalogApi.list(selectedAgent).then((catalog) => {
            const model = catalog.models.find(
              (item) => item.provider_id === info.active_llm?.provider_id && item.model === info.active_llm?.model,
            );
            if (model?.max_input_length != null) {
              setMaxInputLength(model.max_input_length);
            }
          });
        }
      })
      .catch(() => {});
  }, [selectedAgent, canEdit]);

  useEffect(() => {
    refreshEffectiveContextWindow();
  }, [refreshEffectiveContextWindow]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        refreshEffectiveContextWindow();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refreshEffectiveContextWindow]);

  const dynamicTabs = useMemo(() => {
    const baseTabs = [
      {
        key: "reactAgent",
        label: (
          <span className={styles.tabLabel}>
            {t("agentConfig.reactAgentTitle")}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <ReactAgentCard
              language={language}
              savingLang={savingLang}
              onLanguageChange={handleLanguageChange}
              timezone={timezone}
              savingTimezone={savingTimezone}
              onTimezoneChange={handleTimezoneChange}
              requestContext={requestContext}
            />
          </div>
        ),
      },
      {
        key: "agentLoop",
        label: (
          <span className={styles.tabLabel}>
            {t("agentConfig.agentLoopTitle", "Agent Loop Settings")}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <AgentLoopCard />
          </div>
        ),
      },
      {
        key: "llmRetry",
        label: (
          <span className={styles.tabLabel}>
            {t("agentConfig.llmRetryTitle")}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <LlmRetryCard llmRetryEnabled={llmRetryEnabled} />
          </div>
        ),
      },
      {
        key: "llmRateLimiter",
        label: (
          <span className={styles.tabLabel}>
            {t("agentConfig.llmRateLimiterTitle")}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <LlmRateLimiterCard />
          </div>
        ),
      },
    ];

    const contextMapping = CONTEXT_MANAGER_BACKEND_MAPPINGS[contextBackend];
    if (contextMapping) {
      const ContextComponent = contextMapping.component;
      baseTabs.push({
        key: contextMapping.tabKey,
        label: (
          <span className={styles.tabLabel}>
            {t(`agentConfig.${contextMapping.tabKey}Title`)}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <ContextComponent maxInputLength={maxInputLength} />
          </div>
        ),
      });
    }

    const memoryMapping = MEMORY_MANAGER_BACKEND_MAPPINGS[memoryBackend];
    if (memoryMapping) {
      const MemoryComponent = memoryMapping.component;
      baseTabs.push({
        key: memoryMapping.tabKey,
        label: (
          <span className={styles.tabLabel}>
            {t(`agentConfig.${memoryMapping.tabKey}Title`)}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <MemoryComponent requestContext={requestContext} />
          </div>
        ),
      });
    }

    if (memoryBackend === "remelight") {
      baseTabs.push({
        key: "embeddingModel",
        label: (
          <span className={styles.tabLabel}>
            {t("agentConfig.embeddingModelTitle")}
          </span>
        ),
        children: (
          <div className={styles.tabContent}>
            <EmbeddingModelCard requestContext={requestContext} />
          </div>
        ),
      });
    }

    // Add Tool Execution Level tab
    baseTabs.push({
      key: "toolExecutionLevel",
      label: (
        <span className={styles.tabLabel}>
          {t("agentConfig.toolExecutionLevelTitle")}
        </span>
      ),
      children: (
        <div className={styles.tabContent}>
          <ToolExecutionLevelCard
            value={approvalLevel}
            onChange={setApprovalLevel}
            disabled={saving}
          />
        </div>
      ),
    });

    return baseTabs;
  }, [
    t,
    language,
    savingLang,
    timezone,
    savingTimezone,
    handleLanguageChange,
    handleTimezoneChange,
    llmRetryEnabled,
    maxInputLength,
    contextBackend,
    memoryBackend,
    approvalLevel,
    setApprovalLevel,
    saving,
    requestContext,
  ]);

  useEffect(() => {
    const tabKeys = dynamicTabs.map((t) => t.key);
    if (!tabKeys.includes(activeTab)) {
      setActiveTab(tabKeys[0] ?? "reactAgent");
    }
  }, [dynamicTabs, activeTab]);

  if (loading) {
    return (
      <div className={styles.configPage}>
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.configPage}>
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>{error}</span>
          <Button size="small" onClick={fetchConfig} style={{ marginTop: 12 }}>
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  if (isReadOnly && readOnlySummary) {
    return (
      <div className={styles.configPage}>
        <PageHeader parent={t("nav.agent")} current={t("agentConfig.title")} />
        <div className={styles.content}>
          <ReadOnlyConfigSummary summary={readOnlySummary} />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.configPage}>
      <PageHeader parent={t("nav.agent")} current={t("agentConfig.title")} />

      <div className={styles.content}>
        {access?.is_governance && governanceAgentId && (
          <GovernanceConfigAlert
            agentName={searchParams.get("agentName") || governanceAgentId}
            agentId={governanceAgentId}
            ownerUserId={access.owner_user_id}
          />
        )}
        {runtimeState === "pending_reload" && (
          <Alert
            className={styles.reloadAlert}
            type="warning"
            showIcon
            message={t("agentConfig.pendingReloadTitle")}
            description={t("agentConfig.pendingReloadDescription")}
            action={
              <Button
                size="small"
                loading={retryReloading}
                onClick={handleRetryReload}
              >
                {t("agentConfig.retryReload")}
              </Button>
            }
          />
        )}
        <MemoryMaintenanceContext.Provider
          value={{
            needsReindex,
            setNeedsReindex,
            reindexing,
            setReindexing: setLocalReindexing,
            openMemorySettings: () => setActiveTab("remeLightMemory"),
            runtimeStatus,
            checkMemoryStatus,
            configRevision,
          }}
        >
          <Form form={form} layout="vertical" className={styles.form}>
            <Tabs
              className={styles.mainTabs}
              activeKey={activeTab}
              onChange={setActiveTab}
              items={dynamicTabs}
              destroyInactiveTabPane={false}
            />
          </Form>
        </MemoryMaintenanceContext.Provider>
      </div>

      <div className={styles.footerActions}>
        <Button
          onClick={fetchConfig}
          disabled={saving}
          style={{ marginRight: 8 }}
        >
          {t("common.reset")}
        </Button>
        <Button type="primary" onClick={handleSave} loading={saving}>
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default AgentConfigPage;
