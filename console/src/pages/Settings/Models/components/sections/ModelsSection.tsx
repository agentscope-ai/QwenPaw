import React, { useState, useEffect, useMemo } from "react";
import { Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelSlotRequest } from "../../../../../api/types";
import api from "../../../../../api";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
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
  onSaved: () => void;
}

export const ModelsSection = React.memo(function ModelsSection({
  providers,
  activeModels,
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

  const handleProviderChange = (pid: string) => {
    setSelectedProviderId(pid);
    setSelectedModel(undefined);
    setDirty(true);
  };

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    setDirty(true);
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

  const isActive =
    currentSlot &&
    currentSlot.provider_id === selectedProviderId &&
    currentSlot.model === selectedModel;
  const canSave = dirty && !!selectedProviderId && !!selectedModel;

  return (
    <Card className={styles.slotSection}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{t("models.defaultLlm")}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={styles.slotForm}>
          <div className={styles.slotField}>
            <Label className={styles.slotLabel}>{t("models.provider")}</Label>
            <Select
              value={selectedProviderId}
              onValueChange={handleProviderChange}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t("models.selectProvider")} />
              </SelectTrigger>
              <SelectContent>
                {eligible.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className={styles.slotField}>
            <Label className={styles.slotLabel}>{t("models.model")}</Label>
            <Select
              value={selectedModel}
              onValueChange={handleModelChange}
              disabled={!hasModels}
            >
              <SelectTrigger className="w-full">
                <SelectValue
                  placeholder={
                    hasModels
                      ? t("models.selectModel")
                      : t("models.addModelFirst")
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name} ({m.id})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className={[styles.slotField, styles.slotActionField].join(" ")}>
            <Label
              className={[styles.slotLabel, styles.visuallyHiddenLabel].join(
                " ",
              )}
            >
              {t("models.actions")}
            </Label>
            <Button
              disabled={!canSave || saving}
              onClick={handleSave}
              className="w-full"
            >
              <Save className="mr-2 h-4 w-4" />
              {isActive ? t("models.saved") : t("models.save")}
            </Button>
          </div>
        </div>
        <p className={styles.slotDescription}>{t("models.llmDescription")}</p>
      </CardContent>
    </Card>
  );
});
