import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  Filter,
  Gift,
  Plus,
  Image,
  Music,
  Video,
  FileText,
  Type,
  ImagePlay,
} from "lucide-react";
import type { ExtendedModelInfo } from "../../../../../api/types";
import styles from "./OpenRouterFilterSection.module.less";

interface OpenRouterFilterSectionProps {
  showFilters: boolean;
  availableSeries: string[];
  selectedSeries: string[];
  selectedInputModalities: string[];
  showFreeOnly: boolean;
  loadingFilters: boolean;
  discoveredModels: ExtendedModelInfo[];
  saving: boolean;
  isDark: boolean;
  freeTagStyle: CSSProperties;
  onToggleFilters: () => void;
  onSelectedSeriesChange: (series: string[]) => void;
  onSelectedInputModalitiesChange: (modalities: string[]) => void;
  onShowFreeOnlyChange: (checked: boolean) => void;
  onFetchModels: () => void;
  onAddModel: (model: ExtendedModelInfo) => void;
}

const inputModalityOptions = (t: ReturnType<typeof useTranslation>["t"]) => [
  {
    label: (
      <>
        <Image className="inline h-3 w-3 mr-1" /> {t("models.modalityVision")}
      </>
    ),
    value: "image",
  },
  {
    label: (
      <>
        <Music className="inline h-3 w-3 mr-1" /> {t("models.modalityAudio")}
      </>
    ),
    value: "audio",
  },
  {
    label: (
      <>
        <Video className="inline h-3 w-3 mr-1" /> {t("models.modalityVideo")}
      </>
    ),
    value: "video",
  },
  {
    label: (
      <>
        <FileText className="inline h-3 w-3 mr-1" /> {t("models.modalityFile")}
      </>
    ),
    value: "file",
  },
];

function ModelPricing({ model }: { model: ExtendedModelInfo }) {
  const { t } = useTranslation();

  if (!model.pricing?.prompt) {
    return null;
  }

  return (
    <span className={styles.price}>
      ${(parseFloat(model.pricing.prompt) * 1_000_000).toFixed(2)}
      {t("models.perMillionIn")}
      {model.pricing?.completion && (
        <span>
          {" "}
          · ${(parseFloat(model.pricing.completion) * 1_000_000).toFixed(2)}
          {t("models.perMillionOut")}
        </span>
      )}
    </span>
  );
}

export function OpenRouterFilterSection({
  showFilters,
  availableSeries,
  selectedSeries,
  selectedInputModalities,
  showFreeOnly,
  loadingFilters,
  discoveredModels,
  saving,
  isDark,
  freeTagStyle,
  onToggleFilters,
  onSelectedSeriesChange,
  onSelectedInputModalitiesChange,
  onShowFreeOnlyChange,
  onFetchModels,
  onAddModel,
}: OpenRouterFilterSectionProps) {
  const { t } = useTranslation();
  const [providerSearchQuery, setProviderSearchQuery] = useState("");

  const filteredProviders = useMemo(() => {
    const query = providerSearchQuery.trim().toLowerCase();
    if (!query) {
      return availableSeries;
    }
    return availableSeries.filter((provider) =>
      provider.toLowerCase().includes(query),
    );
  }, [availableSeries, providerSearchQuery]);

  const handleToggleProvider = (provider: string, checked: boolean) => {
    if (checked) {
      onSelectedSeriesChange(
        selectedSeries.includes(provider)
          ? selectedSeries
          : [...selectedSeries, provider],
      );
      return;
    }

    onSelectedSeriesChange(selectedSeries.filter((item) => item !== provider));
  };

  const handleSelectAllProviders = () => {
    const merged = new Set([...selectedSeries, ...filteredProviders]);
    onSelectedSeriesChange(Array.from(merged));
  };

  const handleClearProviders = () => {
    const filteredSet = new Set(filteredProviders);
    onSelectedSeriesChange(
      selectedSeries.filter((provider) => !filteredSet.has(provider)),
    );
  };

  const handleToggleModality = (modality: string, checked: boolean) => {
    if (checked) {
      onSelectedInputModalitiesChange(
        selectedInputModalities.includes(modality)
          ? selectedInputModalities
          : [...selectedInputModalities, modality],
      );
      return;
    }

    onSelectedInputModalitiesChange(
      selectedInputModalities.filter((item) => item !== modality),
    );
  };

  return (
    <div className={styles.section}>
      <Button
        variant={showFilters ? "default" : "outline"}
        onClick={onToggleFilters}
        className={`${styles.toggleButton} ${
          showFilters ? styles.toggleButtonExpanded : ""
        }`}
      >
        <Plus className="mr-2 h-4 w-4" />
        {t("models.addModels") || "Add Models"}
      </Button>

      {showFilters && (
        <div className={`${styles.panel} ${isDark ? styles.panelDark : ""}`}>
          <div className={styles.filterGroup}>
            <div className={styles.filterHeader}>
              <div className={styles.filterTitleBlock}>
                <div className={styles.filterLabel}>
                  {t("models.filterByProvider") || "Provider:"}
                </div>
                <div className={styles.providerControls}>
                  <Input
                    value={providerSearchQuery}
                    onChange={(event) =>
                      setProviderSearchQuery(event.target.value)
                    }
                    placeholder={t("models.searchProviderPlaceholder")}
                    className={styles.providerSearchInput}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSelectAllProviders}
                    disabled={filteredProviders.length === 0}
                  >
                    {t("models.selectAllProviders")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleClearProviders}
                    disabled={filteredProviders.length === 0}
                  >
                    {t("models.clearProviderSelection")}
                  </Button>
                </div>
              </div>
            </div>

            <div className={styles.providerList}>
              {filteredProviders.length === 0 ? (
                <div className={styles.providerEmpty}>
                  {t("models.noMatchingProviders")}
                </div>
              ) : (
                filteredProviders.map((provider) => {
                  const checked = selectedSeries.includes(provider);
                  return (
                    <div key={provider} className={styles.providerRow}>
                      <span className={styles.providerName}>{provider}</span>
                      <Switch
                        checked={checked}
                        onCheckedChange={(value) =>
                          handleToggleProvider(provider, value)
                        }
                      />
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className={styles.filterGroup}>
            <div className={styles.filterLabel}>
              {t("models.filterByModality") || "Input Modality:"}
            </div>
            <div className={styles.modalitySwitchGroup}>
              {inputModalityOptions(t).map((option) => {
                const checked = selectedInputModalities.includes(option.value);
                return (
                  <div key={option.value} className={styles.modalitySwitchRow}>
                    <span className={styles.modalitySwitchLabel}>
                      {option.label}
                    </span>
                    <Switch
                      checked={checked}
                      onCheckedChange={(value) =>
                        handleToggleModality(option.value, value)
                      }
                    />
                  </div>
                );
              })}
            </div>
          </div>

          <div className={styles.freeOnlyRow}>
            <div className={styles.freeOnlyLabel}>
              {t("models.filterFreeOnly") || "Free Models Only:"}
            </div>
            <Switch
              checked={showFreeOnly}
              onCheckedChange={onShowFreeOnlyChange}
            />
          </div>

          <Button
            disabled={loadingFilters}
            onClick={onFetchModels}
            className={styles.fetchButton}
          >
            <Filter className="mr-2 h-4 w-4" />
            {t("models.filterModels") || "Filter Models"}
          </Button>

          {discoveredModels.length > 0 && (
            <div className={styles.results}>
              <div className={styles.resultsTitle}>
                {t("models.discovered") || "Available Models:"}
              </div>
              {discoveredModels.map((model) => (
                <div
                  key={model.id}
                  className={`${styles.modelRow} ${
                    isDark ? styles.modelRowDark : ""
                  }`}
                >
                  <div>
                    <div className={styles.modelNameRow}>
                      <span>{model.name}</span>
                      {model.is_free && (
                        <Badge
                          variant="outline"
                          className="text-xs"
                          style={freeTagStyle}
                        >
                          <Gift className="mr-1 h-3 w-3" />
                          {t("models.free")}
                        </Badge>
                      )}
                    </div>
                    <div
                      className={`${styles.modelMeta} ${
                        isDark ? styles.modelMetaDark : ""
                      }`}
                    >
                      <span>{model.provider}</span>
                      {model.input_modalities?.includes("text") && (
                        <Type className="h-3 w-3" />
                      )}
                      {model.input_modalities?.includes("image") && (
                        <Image className="h-3 w-3" />
                      )}
                      {model.input_modalities?.includes("audio") && (
                        <Music className="h-3 w-3" />
                      )}
                      {model.input_modalities?.includes("video") && (
                        <Video className="h-3 w-3" />
                      )}
                      {model.input_modalities?.includes("file") && (
                        <FileText className="h-3 w-3" />
                      )}
                      {model.output_modalities?.includes("image") && (
                        <ImagePlay
                          className="h-3 w-3"
                          style={{ color: isDark ? "#7dd3fc" : "#722ed1" }}
                        />
                      )}
                      <ModelPricing model={model} />
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => onAddModel(model)}
                    disabled={saving}
                  >
                    {t("models.add") || "Add"}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
