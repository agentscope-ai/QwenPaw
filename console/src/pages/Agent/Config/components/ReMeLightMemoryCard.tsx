import { useFormContext, useWatch, Controller } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertTriangle } from "lucide-react";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

export function ReMeLightMemoryCard() {
  const { t } = useTranslation();
  const { register, control } = useFormContext();

  const baseUrl = useWatch({
    control,
    name: "reme_light_memory_config.embedding_model_config.base_url",
  });
  const modelName = useWatch({
    control,
    name: "reme_light_memory_config.embedding_model_config.model_name",
  });
  const embeddingEnabled = !!(baseUrl?.trim() && modelName?.trim());

  return (
    <Card className={styles.formCard}>
      <CardHeader>
        <CardTitle>{t("agentConfig.remeLightMemoryTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <Label title={t("agentConfig.summarizeWhenCompactTooltip")}>
            {t("agentConfig.summarizeWhenCompact")}
          </Label>
          <Controller
            control={control}
            name="reme_light_memory_config.summarize_when_compact"
            render={({ field }) => (
              <Switch
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>

        <div className="space-y-1">
          <Label title={t("agentConfig.autoMemoryIntervalTooltip")}>
            {t("agentConfig.autoMemoryInterval")}
          </Label>
          <Input
            type="number"
            min={1}
            step={1}
            placeholder={t("agentConfig.autoMemoryIntervalPlaceholder")}
            {...register("reme_light_memory_config.auto_memory_interval", {
              valueAsNumber: true,
            })}
          />
        </div>

        <div className="space-y-1">
          <Label title={t("agentConfig.dreamCronTooltip")}>
            {t("agentConfig.dreamCron")}
          </Label>
          <Input
            placeholder={t("agentConfig.dreamCronPlaceholder")}
            {...register("reme_light_memory_config.dream_cron")}
          />
        </div>

        <div className="flex items-center justify-between">
          <Label title={t("agentConfig.rebuildMemoryIndexOnStartTooltip")}>
            {t("agentConfig.rebuildMemoryIndexOnStart")}
          </Label>
          <Controller
            control={control}
            name="reme_light_memory_config.rebuild_memory_index_on_start"
            render={({ field }) => (
              <Switch
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>

        <div className="flex items-center justify-between">
          <Label title={t("agentConfig.recursiveFileWatcherTooltip")}>
            {t("agentConfig.recursiveFileWatcher")}
          </Label>
          <Controller
            control={control}
            name="reme_light_memory_config.recursive_file_watcher"
            render={({ field }) => (
              <Switch
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>

        <Accordion type="multiple">
          <AccordionItem value="autoMemorySearch">
            <AccordionTrigger>
              {t("agentConfig.autoMemorySearchCollapseLabel")}
            </AccordionTrigger>
            <AccordionContent className="space-y-4 pt-2">
              <div className="flex items-center justify-between">
                <Label title={t("agentConfig.autoMemorySearchTooltip")}>
                  {t("agentConfig.autoMemorySearch")}
                </Label>
                <Controller
                  control={control}
                  name="reme_light_memory_config.auto_memory_search_config.enabled"
                  render={({ field }) => (
                    <Switch
                      checked={Boolean(field.value)}
                      onCheckedChange={field.onChange}
                    />
                  )}
                />
              </div>
              <div className="space-y-1">
                <Label title={t("agentConfig.autoMaxResultsTooltip")}>
                  {t("agentConfig.autoMaxResults")}
                </Label>
                <Input
                  type="number"
                  min={1}
                  step={1}
                  {...register(
                    "reme_light_memory_config.auto_memory_search_config.max_results",
                    { valueAsNumber: true },
                  )}
                />
              </div>
              <div className="space-y-1">
                <Label title={t("agentConfig.autoMinScoreTooltip")}>
                  {t("agentConfig.autoMinScore")}
                </Label>
                <Controller
                  control={control}
                  name="reme_light_memory_config.auto_memory_search_config.min_score"
                  render={({ field }) => (
                    <SliderWithValue
                      min={0}
                      max={1}
                      step={0.05}
                      value={field.value}
                      onChange={field.onChange}
                    />
                  )}
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="embeddingConfig">
            <AccordionTrigger>
              {t("agentConfig.embeddingConfigCollapseLabel")}
            </AccordionTrigger>
            <AccordionContent className="space-y-4 pt-2">
              <div className="flex items-start gap-2 rounded-md border border-yellow-300 bg-yellow-50 p-3 text-sm text-yellow-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  {t("agentConfig.embeddingEnableHint")}{" "}
                  {t("agentConfig.embeddingRestartWarning")}
                </span>
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingBaseUrlTooltip")}>
                  {t("agentConfig.embeddingBaseUrl")}
                </Label>
                <Input
                  placeholder={t("agentConfig.embeddingBaseUrlPlaceholder")}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.base_url",
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingModelNameTooltip")}>
                  {t("agentConfig.embeddingModelName")}
                </Label>
                <Input
                  placeholder={t("agentConfig.embeddingModelNamePlaceholder")}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.model_name",
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingApiKeyTooltip")}>
                  {t("agentConfig.embeddingApiKey")}
                </Label>
                <Input
                  type="password"
                  placeholder={t("agentConfig.embeddingApiKeyPlaceholder")}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.api_key",
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingDimensionsTooltip")}>
                  {t("agentConfig.embeddingDimensions")}
                </Label>
                <Input
                  type="number"
                  min={1}
                  step={256}
                  disabled={!embeddingEnabled}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.dimensions",
                    { valueAsNumber: true },
                  )}
                />
              </div>

              <div className="flex items-center justify-between">
                <Label title={t("agentConfig.embeddingEnableCacheTooltip")}>
                  {t("agentConfig.embeddingEnableCache")}
                </Label>
                <Controller
                  control={control}
                  name="reme_light_memory_config.embedding_model_config.enable_cache"
                  render={({ field }) => (
                    <Switch
                      checked={Boolean(field.value)}
                      onCheckedChange={field.onChange}
                      disabled={!embeddingEnabled}
                    />
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingMaxCacheSizeTooltip")}>
                  {t("agentConfig.embeddingMaxCacheSize")}
                </Label>
                <Input
                  type="number"
                  min={1}
                  step={100}
                  disabled={!embeddingEnabled}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.max_cache_size",
                    { valueAsNumber: true },
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingMaxInputLengthTooltip")}>
                  {t("agentConfig.embeddingMaxInputLength")}
                </Label>
                <Input
                  type="number"
                  min={1}
                  step={1024}
                  disabled={!embeddingEnabled}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.max_input_length",
                    { valueAsNumber: true },
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label title={t("agentConfig.embeddingMaxBatchSizeTooltip")}>
                  {t("agentConfig.embeddingMaxBatchSize")}
                </Label>
                <Input
                  type="number"
                  min={1}
                  step={1}
                  disabled={!embeddingEnabled}
                  {...register(
                    "reme_light_memory_config.embedding_model_config.max_batch_size",
                    { valueAsNumber: true },
                  )}
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </CardContent>
    </Card>
  );
}
