import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Switch, Tag } from "@agentscope-ai/design";
import { FilterOutlined, GiftOutlined, PlusOutlined } from "@ant-design/icons";
import {
  SparkImageuploadLine,
  SparkAudiouploadLine,
  SparkVideouploadLine,
  SparkFilePdfLine,
  SparkTextLine,
  SparkTextImageLine,
} from "@agentscope-ai/icons";
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
        <SparkImageuploadLine /> {t("models.modalityVision")}
      </>
    ),
    value: "image",
  },
  {
    label: (
      <>
        <SparkAudiouploadLine /> {t("models.modalityAudio")}
      </>
    ),
    value: "audio",
  },
  {
    label: (
      <>
        <SparkVideouploadLine /> {t("models.modalityVideo")}
      </>
    ),
    value: "video",
  },
  {
    label: (
      <>
        <SparkFilePdfLine /> {t("models.modalityFile")}
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
        type={showFilters ? "primary" : "default"}
        icon={<PlusOutlined />}
        onClick={onToggleFilters}
        className={`${styles.toggleButton} ${
          showFilters ? styles.toggleButtonExpanded : ""
        }`}
      >
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
                    type="text"
                    size="small"
                    onClick={handleSelectAllProviders}
                    disabled={filteredProviders.length === 0}
                  >
                    {t("models.selectAllProviders")}
                  </Button>
                  <Button
                    type="text"
                    size="small"
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
                        size="small"
                        checked={checked}
                        onChange={(value) =>
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
                      size="small"
                      checked={checked}
                      onChange={(value) =>
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
            <Switch checked={showFreeOnly} onChange={onShowFreeOnlyChange} />
          </div>

          <Button
            type="primary"
            icon={<FilterOutlined />}
            onClick={onFetchModels}
            loading={loadingFilters}
            className={styles.fetchButton}
          >
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
                        <Tag
                          style={{
                            fontSize: 11,
                            lineHeight: "16px",
                            marginRight: 0,
                            ...freeTagStyle,
                          }}
                        >
                          <GiftOutlined
                            style={{ fontSize: 10, marginRight: 3 }}
                          />
                          {t("models.free")}
                        </Tag>
                      )}
                    </div>
                    <div
                      className={`${styles.modelMeta} ${
                        isDark ? styles.modelMetaDark : ""
                      }`}
                    >
                      <span>{model.provider}</span>
                      {model.input_modalities?.includes("text") && (
                        <SparkTextLine style={{ fontSize: 12 }} />
                      )}
                      {model.input_modalities?.includes("image") && (
                        <SparkImageuploadLine style={{ fontSize: 12 }} />
                      )}
                      {model.input_modalities?.includes("audio") && (
                        <SparkAudiouploadLine style={{ fontSize: 12 }} />
                      )}
                      {model.input_modalities?.includes("video") && (
                        <SparkVideouploadLine style={{ fontSize: 12 }} />
                      )}
                      {model.input_modalities?.includes("file") && (
                        <SparkFilePdfLine style={{ fontSize: 12 }} />
                      )}
                      {model.output_modalities?.includes("image") && (
                        <SparkTextImageLine
                          style={{
                            fontSize: 12,
                            color: isDark ? "#7dd3fc" : "#722ed1",
                          }}
                        />
                      )}
                      <ModelPricing model={model} />
                    </div>
                  </div>
                  <Button
                    size="small"
                    type="primary"
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
