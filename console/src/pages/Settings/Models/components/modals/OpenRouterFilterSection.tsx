import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { Button, Checkbox, Switch, Tag } from "@agentscope-ai/design";
import { FilterOutlined, GiftOutlined } from "@ant-design/icons";
import {
  SparkTextLine,
  SparkImageuploadLine,
  SparkAudiouploadLine,
  SparkVideouploadLine,
  SparkFilePdfLine,
  SparkTextImageLine,
} from "@agentscope-ai/icons";
import type { ExtendedModelInfo } from "../../../../../api/types";
import styles from "./OpenRouterFilterSection.module.less";

interface OpenRouterFilterSectionProps {
  showFilters: boolean;
  availableSeries: string[];
  selectedSeries: string[];
  selectedInputModality: string | null;
  showFreeOnly: boolean;
  loadingFilters: boolean;
  discoveredModels: ExtendedModelInfo[];
  saving: boolean;
  isDark: boolean;
  freeTagStyle: CSSProperties;
  onToggleFilters: () => void;
  onSelectedSeriesChange: (series: string[]) => void;
  onSelectedInputModalityChange: (modality: string | null) => void;
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
  {
    label: (
      <>
        <SparkTextLine /> {t("models.modalityText")}
      </>
    ),
    value: "text",
  },
];

function ModelPricing({ model }: { model: ExtendedModelInfo }) {
  const { t } = useTranslation();

  if (!model.pricing?.prompt) {
    return null;
  }

  return (
    <span className={styles.price}>
      $
      {(parseFloat(model.pricing.prompt) * 1_000_000).toFixed(2)}
      {t("models.perMillionIn")}
      {model.pricing?.completion && (
        <span>
          {" "}
          · ${
            (parseFloat(model.pricing.completion) * 1_000_000).toFixed(2)
          }
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
  selectedInputModality,
  showFreeOnly,
  loadingFilters,
  discoveredModels,
  saving,
  isDark,
  freeTagStyle,
  onToggleFilters,
  onSelectedSeriesChange,
  onSelectedInputModalityChange,
  onShowFreeOnlyChange,
  onFetchModels,
  onAddModel,
}: OpenRouterFilterSectionProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.section}>
      <Button
        type={showFilters ? "primary" : "default"}
        icon={<FilterOutlined />}
        onClick={onToggleFilters}
        className={`${styles.toggleButton} ${showFilters ? styles.toggleButtonExpanded : ""}`}
      >
        {t("models.filterModels") || "Filter Models"}
      </Button>

      {showFilters && (
        <div className={`${styles.panel} ${isDark ? styles.panelDark : ""}`}>
          <div className={styles.filterGroup}>
            <div className={styles.filterLabel}>
              {t("models.filterByProvider") || "Provider:"}
            </div>
            <Checkbox.Group
              options={availableSeries.map((series) => ({
                label: series,
                value: series,
              }))}
              value={selectedSeries}
              onChange={(values) => onSelectedSeriesChange(values as string[])}
              className={styles.checkboxGroup}
            />
          </div>

          <div className={styles.filterGroup}>
            <div className={styles.filterLabel}>
              {t("models.filterByModality") || "Input Modality:"}
            </div>
            <Checkbox.Group
              options={inputModalityOptions(t)}
              value={selectedInputModality ? [selectedInputModality] : []}
              onChange={(values) =>
                onSelectedInputModalityChange(
                  values.length > 0 ? (values[0] as string) : null,
                )
              }
              className={styles.checkboxGroup}
            />
          </div>

          <div className={styles.freeOnlyRow}>
            <div className={styles.freeOnlyLabel}>
              {t("models.filterFreeOnly") || "Free Models Only"}
            </div>
            <Switch checked={showFreeOnly} onChange={onShowFreeOnlyChange} />
          </div>

          <Button
            type="primary"
            onClick={onFetchModels}
            loading={loadingFilters}
            className={styles.fetchButton}
          >
            {t("models.getModels") || "Get Models"}
          </Button>

          {discoveredModels.length > 0 && (
            <div className={styles.results}>
              <div className={styles.resultsTitle}>
                {t("models.discovered") || "Available Models:"}
              </div>
              {discoveredModels.map((model) => (
                <div
                  key={model.id}
                  className={`${styles.modelRow} ${isDark ? styles.modelRowDark : ""}`}
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
                          <GiftOutlined style={{ fontSize: 10, marginRight: 3 }} />
                          {t("models.free")}
                        </Tag>
                      )}
                    </div>
                    <div
                      className={`${styles.modelMeta} ${isDark ? styles.modelMetaDark : ""}`}
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
                          style={{ fontSize: 12, color: isDark ? "#7dd3fc" : "#722ed1" }}
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