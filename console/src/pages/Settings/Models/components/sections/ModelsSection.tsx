import { useState, useEffect, useMemo } from "react";
import { SaveOutlined } from "@ant-design/icons";
import { Select, Button, Card, Switch } from "@agentscope-ai/design";
import type {
  RoutingConfig,
  RoutingMode,
  ModelSlotRequest,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import {
  hasConfiguredRoutingSlot,
  isLoopbackBaseUrl,
} from "../../../../../utils/routing";
import styles from "../../index.module.less";

interface ModelsSectionProps {
  providers: Array<{
    id: string;
    name: string;
    models?: Array<{ id: string; name: string; is_free?: boolean }>;
    extra_models?: Array<{ id: string; name: string; is_free?: boolean }>;
    base_url?: string;
    api_key?: string;
    is_custom: boolean;
    is_local?: boolean;
    require_api_key?: boolean;
  }>;
  activeModels: {
    active_llm?: {
      provider_id?: string;
      model?: string;
    };
  } | null;
  routingConfig: RoutingConfig | null;
  onSaved: () => void;
}

function emptySlot() {
  return { provider_id: "", model: "" };
}

function isLocalRoutingProvider(
  provider: ModelsSectionProps["providers"][number],
) {
  return Boolean(provider.is_local || isLoopbackBaseUrl(provider.base_url));
}

export function ModelsSection({
  providers,
  activeModels,
  routingConfig,
  onSaved,
}: ModelsSectionProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [selectedProviderId, setSelectedProviderId] = useState<
    string | undefined
  >(undefined);
  const [selectedModel, setSelectedModel] = useState<string | undefined>(
    undefined,
  );
  const [dirty, setDirty] = useState(false);
  const [routingEnabled, setRoutingEnabled] = useState(false);
  const [routingMode, setRoutingMode] = useState<RoutingMode>("local_first");
  const [localProviderId, setLocalProviderId] = useState<string | undefined>();
  const [localModelId, setLocalModelId] = useState<string | undefined>();
  const [cloudProviderId, setCloudProviderId] = useState<string | undefined>();
  const [cloudModelId, setCloudModelId] = useState<string | undefined>();
  const [routingDirty, setRoutingDirty] = useState(false);
  const { message } = useAppMessage();

  const currentSlot = activeModels?.active_llm;

  const eligible = useMemo(
    () =>
      providers.filter((p) => {
        const hasModels =
          (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
        if (!hasModels) return false;
        if (p.require_api_key === false) return !!p.base_url;
        if (p.is_custom) return !!p.base_url;
        if (p.require_api_key ?? true) return !!p.api_key;
        return true;
      }),
    [providers],
  );

  const localEligible = useMemo(
    () => eligible.filter((provider) => isLocalRoutingProvider(provider)),
    [eligible],
  );

  const cloudEligible = useMemo(
    () => eligible.filter((provider) => !isLocalRoutingProvider(provider)),
    [eligible],
  );

  useEffect(() => {
    if (currentSlot) {
      setSelectedProviderId(currentSlot.provider_id || undefined);
      setSelectedModel(currentSlot.model || undefined);
    }
    setDirty(false);
  }, [currentSlot?.provider_id, currentSlot?.model]);

  const chosenProvider = providers.find((p) => p.id === selectedProviderId);
  const modelOptions = [
    ...(chosenProvider?.models ?? []),
    ...(chosenProvider?.extra_models ?? []),
  ];
  const hasModels = modelOptions.length > 0;
  const localProvider = providers.find((p) => p.id === localProviderId);
  const localModelOptions = [
    ...(localProvider?.models ?? []),
    ...(localProvider?.extra_models ?? []),
  ];
  const cloudProvider = providers.find((p) => p.id === cloudProviderId);
  const cloudModelOptions = [
    ...(cloudProvider?.models ?? []),
    ...(cloudProvider?.extra_models ?? []),
  ];

  const handleProviderChange = (pid: string) => {
    setSelectedProviderId(pid);
    setSelectedModel(undefined);
    setDirty(true);
  };

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    setDirty(true);
  };

  useEffect(() => {
    if (!routingConfig) {
      return;
    }
    setRoutingEnabled(Boolean(routingConfig.enabled));
    setRoutingMode(routingConfig.mode ?? "local_first");
    setLocalProviderId(routingConfig.local?.provider_id || undefined);
    setLocalModelId(routingConfig.local?.model || undefined);
    setCloudProviderId(routingConfig.cloud?.provider_id || undefined);
    setCloudModelId(routingConfig.cloud?.model || undefined);
    setRoutingDirty(false);
  }, [routingConfig]);

  const handleRoutingEnabledChange = (enabled: boolean) => {
    setRoutingEnabled(enabled);
    setRoutingDirty(true);
  };

  const handleRoutingModeChange = (mode: RoutingMode) => {
    setRoutingMode(mode);
    setRoutingDirty(true);
  };

  const handleLocalProviderChange = (providerId: string) => {
    setLocalProviderId(providerId);
    setLocalModelId(undefined);
    setRoutingDirty(true);
  };

  const handleLocalModelChange = (modelId: string) => {
    setLocalModelId(modelId);
    setRoutingDirty(true);
  };

  const handleCloudProviderChange = (providerId: string) => {
    setCloudProviderId(providerId);
    setCloudModelId(undefined);
    setRoutingDirty(true);
  };

  const handleCloudModelChange = (modelId: string) => {
    setCloudModelId(modelId);
    setRoutingDirty(true);
  };

  const handleSave = async () => {
    if (!selectedProviderId || !selectedModel) return;

    const selectedProvider = providers.find((p) => p.id === selectedProviderId);
    const selectedModelInfo = [
      ...(selectedProvider?.models ?? []),
      ...(selectedProvider?.extra_models ?? []),
    ].find((model) => model.id === selectedModel);

    if (selectedProvider && selectedModelInfo) {
      const confirmed = await confirmFreeModelSwitch({
        provider: selectedProvider,
        model: selectedModelInfo,
        t,
      });
      if (!confirmed) return;
    }

    const body: ModelSlotRequest = {
      provider_id: selectedProviderId,
      model: selectedModel,
      scope: "global",
    };

    setSaving(true);
    try {
      await api.setActiveLlm(body);
      message.success(t("models.llmModelUpdated"));
      setDirty(false);
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveRouting = async () => {
    const nextRouting: RoutingConfig = {
      enabled: routingEnabled,
      mode: routingMode,
      local:
        localProviderId && localModelId
          ? { provider_id: localProviderId, model: localModelId }
          : emptySlot(),
      cloud:
        cloudProviderId && cloudModelId
          ? { provider_id: cloudProviderId, model: cloudModelId }
          : null,
    };

    const selectedSlot =
      routingMode === "local_first" ? nextRouting.local : nextRouting.cloud;
    const cloudSlot = nextRouting.cloud;

    if (nextRouting.enabled && !hasConfiguredRoutingSlot(selectedSlot)) {
      message.warning(
        t("models.routingConfigureSelectedSlot", {
          defaultValue:
            "Configure the selected mode slot before enabling routing.",
        }),
      );
      return;
    }

    if (
      hasConfiguredRoutingSlot(nextRouting.local) &&
      hasConfiguredRoutingSlot(nextRouting.cloud) &&
      nextRouting.local.provider_id === nextRouting.cloud.provider_id &&
      nextRouting.local.model === nextRouting.cloud.model
    ) {
      message.warning(
        t("models.routingDistinctSlots", {
          defaultValue:
            "Local and cloud slots must point to different provider/model pairs.",
        }),
      );
      return;
    }

    if (
      hasConfiguredRoutingSlot(nextRouting.local) &&
      !localEligible.some(
        (provider) => provider.id === nextRouting.local.provider_id,
      )
    ) {
      message.warning(
        t("models.routingLocalMustBeLocal", {
          defaultValue: "Local slot must use a local or loopback provider.",
        }),
      );
      return;
    }

    if (
      hasConfiguredRoutingSlot(cloudSlot) &&
      !cloudEligible.some((provider) => provider.id === cloudSlot.provider_id)
    ) {
      message.warning(
        t("models.routingCloudMustBeCloud", {
          defaultValue: "Cloud slot must use a non-local provider.",
        }),
      );
      return;
    }

    setSaving(true);
    try {
      await api.setRoutingConfig(nextRouting);
      message.success(
        nextRouting.enabled
          ? t("models.routingSaved", {
              defaultValue: "Routing mode saved.",
            })
          : t("models.routingDisabled", {
              defaultValue: "Routing mode disabled.",
            }),
      );
      setRoutingDirty(false);
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const isActive =
    currentSlot &&
    currentSlot.provider_id === selectedProviderId &&
    currentSlot.model === selectedModel;
  const canSave = dirty && !!selectedProviderId && !!selectedModel;
  const draftLocalSlot =
    localProviderId && localModelId
      ? { provider_id: localProviderId, model: localModelId }
      : emptySlot();
  const draftCloudSlot =
    cloudProviderId && cloudModelId
      ? { provider_id: cloudProviderId, model: cloudModelId }
      : null;
  const selectedDraftSlot =
    routingMode === "local_first" ? draftLocalSlot : draftCloudSlot;
  const routingDraftDistinct = !(
    hasConfiguredRoutingSlot(draftLocalSlot) &&
    hasConfiguredRoutingSlot(draftCloudSlot) &&
    draftLocalSlot.provider_id === draftCloudSlot.provider_id &&
    draftLocalSlot.model === draftCloudSlot.model
  );
  const routingDraftLocalValid =
    !hasConfiguredRoutingSlot(draftLocalSlot) ||
    localEligible.some(
      (provider) => provider.id === draftLocalSlot.provider_id,
    );
  const routingDraftCloudValid =
    !hasConfiguredRoutingSlot(draftCloudSlot) ||
    cloudEligible.some(
      (provider) => provider.id === draftCloudSlot.provider_id,
    );
  const canSaveRouting =
    routingDirty &&
    (!routingEnabled ||
      (hasConfiguredRoutingSlot(selectedDraftSlot) &&
        routingDraftDistinct &&
        routingDraftLocalValid &&
        routingDraftCloudValid));

  return (
    <>
      <Card className={styles.slotSection} title={t("models.defaultLlm")}>
        <div className={styles.slotForm}>
          <div className={styles.slotField}>
            <label className={styles.slotLabel}>{t("models.provider")}</label>
            <Select
              style={{ width: "100%" }}
              placeholder={t("models.selectProvider")}
              value={selectedProviderId}
              onChange={handleProviderChange}
              options={eligible.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
            />
          </div>

          <div className={styles.slotField}>
            <label className={styles.slotLabel}>{t("models.model")}</label>
            <Select
              style={{ width: "100%" }}
              placeholder={
                hasModels ? t("models.selectModel") : t("models.addModelFirst")
              }
              disabled={!hasModels}
              showSearch
              optionFilterProp="label"
              value={selectedModel}
              onChange={handleModelChange}
              options={modelOptions.map((m) => ({
                value: m.id,
                label: `${m.name} (${m.id})`,
              }))}
            />
          </div>

          <div className={[styles.slotField, styles.slotActionField].join(" ")}>
            <label
              className={[styles.slotLabel, styles.visuallyHiddenLabel].join(
                " ",
              )}
            >
              {t("models.actions")}
            </label>
            <Button
              type="primary"
              loading={saving}
              disabled={!canSave}
              onClick={handleSave}
              block
              icon={<SaveOutlined />}
            >
              {isActive ? t("models.saved") : t("models.save")}
            </Button>
          </div>
        </div>
        <p className={styles.slotDescription}>{t("models.llmDescription")}</p>
      </Card>

      <Card
        className={styles.slotSection}
        title={
          <div className={styles.routingTitleBar}>
            <span>
              {t("models.routingTitle", {
                defaultValue: "Routing",
              })}
            </span>
            <div className={styles.routingToggle}>
              <span className={styles.slotLabel}>
                {t("models.routingEnabled", { defaultValue: "Enabled" })}
              </span>
              <Switch
                checked={routingEnabled}
                onChange={handleRoutingEnabledChange}
              />
            </div>
          </div>
        }
      >
        <div className={styles.slotForm}>
          <div className={styles.slotField}>
            <label className={styles.slotLabel}>
              {t("models.routingMode", {
                defaultValue: "Mode",
              })}
            </label>
            <Select
              style={{ width: "100%" }}
              disabled={!routingEnabled}
              value={routingMode}
              onChange={handleRoutingModeChange}
              options={[
                {
                  value: "local_first",
                  label: t("models.routingModeLocal", {
                    defaultValue: "Local",
                  }),
                },
                {
                  value: "cloud_first",
                  label: t("models.routingModeCloud", {
                    defaultValue: "Cloud",
                  }),
                },
              ]}
            />
          </div>

          <div className={styles.slotField}>
            <label className={styles.slotLabel}>
              {t("models.routingLocalProvider", {
                defaultValue: "Local Provider",
              })}
            </label>
            <Select
              style={{ width: "100%" }}
              placeholder={t("models.selectProvider")}
              disabled={!routingEnabled}
              value={localProviderId}
              onChange={handleLocalProviderChange}
              options={localEligible.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
            />
          </div>

          <div className={styles.slotField}>
            <label className={styles.slotLabel}>
              {t("models.routingLocalModel", { defaultValue: "Local Model" })}
            </label>
            <Select
              style={{ width: "100%" }}
              placeholder={t("models.selectModel")}
              disabled={!routingEnabled || localModelOptions.length === 0}
              value={localModelId}
              onChange={handleLocalModelChange}
              options={localModelOptions.map((m) => ({
                value: m.id,
                label: `${m.name} (${m.id})`,
              }))}
            />
          </div>

          <div className={styles.slotField}>
            <label className={styles.slotLabel}>
              {t("models.routingCloudProvider", {
                defaultValue: "Cloud Provider",
              })}
            </label>
            <Select
              style={{ width: "100%" }}
              placeholder={t("models.selectProvider")}
              disabled={!routingEnabled}
              value={cloudProviderId}
              onChange={handleCloudProviderChange}
              options={cloudEligible.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
            />
          </div>

          <div className={styles.slotField}>
            <label className={styles.slotLabel}>
              {t("models.routingCloudModel", { defaultValue: "Cloud Model" })}
            </label>
            <Select
              style={{ width: "100%" }}
              placeholder={t("models.selectModel")}
              disabled={!routingEnabled || cloudModelOptions.length === 0}
              value={cloudModelId}
              onChange={handleCloudModelChange}
              options={cloudModelOptions.map((m) => ({
                value: m.id,
                label: `${m.name} (${m.id})`,
              }))}
            />
          </div>

          <div
            className={styles.slotField}
            style={{ flex: "0 0 auto", minWidth: "120px" }}
          >
            <label
              className={styles.slotLabel}
              style={{ visibility: "hidden" }}
            >
              {t("models.actions")}
            </label>
            <Button
              type="primary"
              loading={saving}
              disabled={!canSaveRouting}
              onClick={handleSaveRouting}
              block
              icon={<SaveOutlined />}
            >
              {routingDirty ? t("models.save") : t("models.saved")}
            </Button>
          </div>
        </div>
      </Card>
    </>
  );
}
