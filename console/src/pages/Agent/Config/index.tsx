import { useState, useMemo, useEffect } from "react";
import { FormProvider, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAgentConfig } from "./useAgentConfig.tsx";
import {
  ReactAgentCard,
  LlmRetryCard,
  LlmRateLimiterCard,
  ToolExecutionLevelCard,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
} from "@/constants/backendMappings";
import api from "@/api";
import styles from "./index.module.less";

function AgentConfigPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("reactAgent");
  const {
    form,
    loading,
    saving,
    error,
    language,
    savingLang,
    timezone,
    savingTimezone,
    approvalLevel,
    setApprovalLevel,
    fetchConfig,
    handleSave,
    handleLanguageChange,
    handleTimezoneChange,
    languageConfirmDialog,
  } = useAgentConfig();

  const llmRetryEnabled =
    useWatch({ control: form.control, name: "llm_retry_enabled" }) ?? true;
  const contextBackend =
    (useWatch({
      control: form.control,
      name: "context_manager_backend",
    }) as string) || "light";
  const memoryBackend =
    (useWatch({
      control: form.control,
      name: "memory_manager_backend",
    }) as string) || "remelight";

  const [maxInputLength, setMaxInputLength] = useState(131072);
  useEffect(() => {
    api
      .getActiveModels({ scope: "effective" })
      .then((info) => {
        if (info.active_llm) {
          return api.listProviders().then((providers) => {
            for (const p of providers) {
              const all = [...(p.models ?? []), ...(p.extra_models ?? [])];
              const m = all.find((m) => m.id === info.active_llm?.model);
              if (m?.max_input_length) {
                setMaxInputLength(m.max_input_length);
                return;
              }
            }
          });
        }
      })
      .catch(() => {});
  }, []);

  const dynamicTabs = useMemo(() => {
    const baseTabs = [
      {
        key: "reactAgent",
        label: t("agentConfig.reactAgentTitle"),
        children: (
          <div className={styles.tabContent}>
            <ReactAgentCard
              language={language}
              savingLang={savingLang}
              onLanguageChange={handleLanguageChange}
              timezone={timezone}
              savingTimezone={savingTimezone}
              onTimezoneChange={handleTimezoneChange}
            />
          </div>
        ),
      },
      {
        key: "llmRetry",
        label: t("agentConfig.llmRetryTitle"),
        children: (
          <div className={styles.tabContent}>
            <LlmRetryCard llmRetryEnabled={Boolean(llmRetryEnabled)} />
          </div>
        ),
      },
      {
        key: "llmRateLimiter",
        label: t("agentConfig.llmRateLimiterTitle"),
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
        label: t(`agentConfig.${contextMapping.tabKey}Title`),
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
        label: t(`agentConfig.${memoryMapping.tabKey}Title`),
        children: (
          <div className={styles.tabContent}>
            <MemoryComponent />
          </div>
        ),
      });
    }

    baseTabs.push({
      key: "toolExecutionLevel",
      label: t("agentConfig.toolExecutionLevelTitle"),
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
  ]);

  useEffect(() => {
    const tabKeys = dynamicTabs.map((tab) => tab.key);
    if (!tabKeys.includes(activeTab)) {
      setActiveTab(tabKeys[0] ?? "reactAgent");
    }
  }, [dynamicTabs, activeTab]);

  if (loading) {
    return (
      <div className={styles.configPage}>
        <div className={styles.centerState}>
          <Loader2 className="animate-spin" />
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
          <Button
            size="sm"
            variant="outline"
            onClick={fetchConfig}
            className="mt-3"
          >
            {t("environments.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.configPage}>
      <PageHeader parent={t("nav.agent")} current={t("agentConfig.title")} />

      <div className={styles.content}>
        <FormProvider {...form}>
          <Tabs
            className={styles.mainTabs}
            value={activeTab}
            onValueChange={setActiveTab}
          >
            <TabsList className="flex flex-wrap h-auto gap-1 mb-4">
              {dynamicTabs.map((tab) => (
                <TabsTrigger key={tab.key} value={tab.key}>
                  <span className={styles.tabLabel}>{tab.label}</span>
                </TabsTrigger>
              ))}
            </TabsList>
            {dynamicTabs.map((tab) => (
              <TabsContent key={tab.key} value={tab.key}>
                {tab.children}
              </TabsContent>
            ))}
          </Tabs>
        </FormProvider>
      </div>

      <div className={styles.footerActions}>
        <Button
          variant="outline"
          onClick={fetchConfig}
          disabled={saving}
          className="mr-2"
        >
          {t("common.reset")}
        </Button>
        <Button onClick={handleSave} disabled={saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t("common.save")}
        </Button>
      </div>

      {languageConfirmDialog}
    </div>
  );
}

export default AgentConfigPage;
