import { useState, useEffect, useMemo } from "react";
import { SaveOutlined } from "@ant-design/icons";
import { Button, message, Input } from "@agentscope-ai/design";
import type { ModelSlotRequest } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";
import { MediaPrepassSection } from "./MediaPrepassSection";
import { ModelSlotSection } from "./ModelSlotSection";

interface ModelsSectionProps {
  providers: Array<{
    id: string;
    name: string;
    models?: Array<{ id: string; name: string }>;
    extra_models?: Array<{ id: string; name: string }>;
    current_base_url?: string;
    has_api_key: boolean;
    is_custom: boolean;
    is_local?: boolean;
  }>;
  activeModels: {
    active_llm?: {
      provider_id?: string;
      model?: string;
    };
    active_vlm?: {
      provider_id?: string;
      model?: string;
    };
    active_vlm_fallbacks?: Array<{
      provider_id?: string;
      model?: string;
    }>;
    vision?: {
      image?: {
        enabled?: boolean;
        attachments_mode?: string;
        max_images?: number;
        timeout_seconds?: number;
        max_output_chars?: number;
        prompt_override?: string;
      };
      audio?: {
        enabled?: boolean;
        attachments_mode?: string;
        max_items?: number;
        timeout_seconds?: number;
        max_output_chars?: number;
        prompt_override?: string;
      };
      video?: {
        enabled?: boolean;
        attachments_mode?: string;
        max_items?: number;
        timeout_seconds?: number;
        max_output_chars?: number;
        prompt_override?: string;
      };
    };
  } | null;
  onSaved: () => void;
}

export function ModelsSection({
  providers,
  activeModels,
  onSaved,
}: ModelsSectionProps) {
  const { t } = useTranslation();
  const [savingLlm, setSavingLlm] = useState(false);
  const [savingVlm, setSavingVlm] = useState(false);
  const [selectedLlmProviderId, setSelectedLlmProviderId] = useState<
    string | undefined
  >(undefined);
  const [selectedLlmModel, setSelectedLlmModel] = useState<string | undefined>(
    undefined,
  );
  const [selectedVlmProviderId, setSelectedVlmProviderId] = useState<
    string | undefined
  >(undefined);
  const [selectedVlmModel, setSelectedVlmModel] = useState<string | undefined>(
    undefined,
  );
  const [llmDirty, setLlmDirty] = useState(false);
  const [vlmDirty, setVlmDirty] = useState(false);
  const [savingFallbacks, setSavingFallbacks] = useState(false);
  const [fallbackDirty, setFallbackDirty] = useState(false);
  const [fallbackText, setFallbackText] = useState("");

  const currentLlmSlot = activeModels?.active_llm;
  const currentVlmSlot = activeModels?.active_vlm;
  const currentVlmFallbacks = activeModels?.active_vlm_fallbacks ?? [];

  const eligible = useMemo(
    () =>
      providers.filter((p) => {
        if (p.is_local) return (p.models?.length ?? 0) > 0;
        return p.is_custom ? !!p.current_base_url : p.has_api_key;
      }),
    [providers],
  );

  useEffect(() => {
    if (currentLlmSlot) {
      setSelectedLlmProviderId(currentLlmSlot.provider_id || undefined);
      setSelectedLlmModel(currentLlmSlot.model || undefined);
    }
    setLlmDirty(false);
  }, [currentLlmSlot?.provider_id, currentLlmSlot?.model]);

  useEffect(() => {
    if (currentVlmSlot) {
      setSelectedVlmProviderId(currentVlmSlot.provider_id || undefined);
      setSelectedVlmModel(currentVlmSlot.model || undefined);
    }
    setVlmDirty(false);
  }, [currentVlmSlot?.provider_id, currentVlmSlot?.model]);

  useEffect(() => {
    const text = currentVlmFallbacks
      .map((f) => `${f.provider_id || ""}/${f.model || ""}`)
      .filter((line) => line !== "/")
      .join("\n");
    setFallbackText(text);
    setFallbackDirty(false);
  }, [currentVlmFallbacks]);

  const llmProvider = providers.find((p) => p.id === selectedLlmProviderId);
  const llmModelOptions = llmProvider?.models ?? [];
  const hasLlmModels = llmModelOptions.length > 0;

  const vlmProvider = providers.find((p) => p.id === selectedVlmProviderId);
  const vlmModelOptions = vlmProvider?.models ?? [];
  const hasVlmModels = vlmModelOptions.length > 0;
  const providerOptions = useMemo(
    () =>
      eligible.map((p) => ({
        value: p.id,
        label: p.name,
      })),
    [eligible],
  );

  const handleLlmProviderChange = (pid: string) => {
    setSelectedLlmProviderId(pid);
    setSelectedLlmModel(undefined);
    setLlmDirty(true);
  };

  const handleLlmModelChange = (model: string) => {
    setSelectedLlmModel(model);
    setLlmDirty(true);
  };

  const handleVlmProviderChange = (pid: string) => {
    setSelectedVlmProviderId(pid);
    setSelectedVlmModel(undefined);
    setVlmDirty(true);
  };

  const handleVlmModelChange = (model: string) => {
    setSelectedVlmModel(model);
    setVlmDirty(true);
  };

  const handleSaveLlm = async () => {
    if (!selectedLlmProviderId || !selectedLlmModel) return;

    const body: ModelSlotRequest = {
      provider_id: selectedLlmProviderId,
      model: selectedLlmModel,
    };

    setSavingLlm(true);
    try {
      await api.setActiveLlm(body);
      message.success(t("models.llmModelUpdated"));
      setLlmDirty(false);
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
    } finally {
      setSavingLlm(false);
    }
  };

  const handleSaveVlm = async () => {
    if (!selectedVlmProviderId || !selectedVlmModel) return;

    const body: ModelSlotRequest = {
      provider_id: selectedVlmProviderId,
      model: selectedVlmModel,
    };

    setSavingVlm(true);
    try {
      await api.setActiveVlm(body);
      message.success(t("models.vlmModelUpdated"));
      setVlmDirty(false);
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
    } finally {
      setSavingVlm(false);
    }
  };

  const handleSaveFallbacks = async () => {
    let fallbacks: Array<{ provider_id: string; model: string }> = [];
    try {
      fallbacks = fallbackText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const idx = line.indexOf("/");
          if (idx <= 0 || idx >= line.length - 1) {
            throw new Error(t("models.vlmFallbackInvalidFormat", { line }));
          }
          return {
            provider_id: line.slice(0, idx).trim(),
            model: line.slice(idx + 1).trim(),
          };
        });
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
      return;
    }

    setSavingFallbacks(true);
    try {
      await api.setActiveVlmFallbacks({ fallbacks });
      message.success(t("models.vlmFallbackUpdated"));
      setFallbackDirty(false);
      onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSave");
      message.error(errMsg);
    } finally {
      setSavingFallbacks(false);
    }
  };


  const llmActive =
    currentLlmSlot &&
    currentLlmSlot.provider_id === selectedLlmProviderId &&
    currentLlmSlot.model === selectedLlmModel;
  const canSaveLlm = llmDirty && !!selectedLlmProviderId && !!selectedLlmModel;

  const vlmActive =
    currentVlmSlot &&
    currentVlmSlot.provider_id === selectedVlmProviderId &&
    currentVlmSlot.model === selectedVlmModel;
  const canSaveVlm = vlmDirty && !!selectedVlmProviderId && !!selectedVlmModel;

  return (
    <>
      <ModelSlotSection
        titleKey="models.llmConfiguration"
        currentSlot={currentLlmSlot}
        selectedProviderId={selectedLlmProviderId}
        selectedModel={selectedLlmModel}
        providerOptions={providerOptions}
        modelOptions={llmModelOptions.map((m) => ({
          value: m.id,
          label: `${m.name} (${m.id})`,
        }))}
        hasModels={hasLlmModels}
        saving={savingLlm}
        canSave={canSaveLlm}
        isActive={!!llmActive}
        onProviderChange={handleLlmProviderChange}
        onModelChange={handleLlmModelChange}
        onSave={handleSaveLlm}
      />

      <div className={styles.slotSection}>
        <div className={styles.slotHeader}>
          <h3 className={styles.slotTitle}>{t("models.vlmFallbackChain")}</h3>
        </div>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>
            {t("models.vlmFallbackOnePerLine")}
          </label>
          <Input.TextArea
            rows={4}
            value={fallbackText}
            onChange={(e) => {
              setFallbackText(e.target.value);
              setFallbackDirty(true);
            }}
            placeholder={t("models.vlmFallbackPlaceholder")}
          />
        </div>
        <div className={styles.slotActions}>
          <Button
            type="primary"
            loading={savingFallbacks}
            disabled={!fallbackDirty}
            onClick={handleSaveFallbacks}
            icon={<SaveOutlined />}
          >
            {t("models.save")}
          </Button>
        </div>
      </div>

      <ModelSlotSection
        titleKey="models.vlmConfiguration"
        currentSlot={currentVlmSlot}
        selectedProviderId={selectedVlmProviderId}
        selectedModel={selectedVlmModel}
        providerOptions={providerOptions}
        modelOptions={vlmModelOptions.map((m) => ({
          value: m.id,
          label: `${m.name} (${m.id})`,
        }))}
        hasModels={hasVlmModels}
        saving={savingVlm}
        canSave={canSaveVlm}
        isActive={!!vlmActive}
        onProviderChange={handleVlmProviderChange}
        onModelChange={handleVlmModelChange}
        onSave={handleSaveVlm}
      />

      <MediaPrepassSection vision={activeModels?.vision} onSaved={onSaved} />
    </>
  );
}
