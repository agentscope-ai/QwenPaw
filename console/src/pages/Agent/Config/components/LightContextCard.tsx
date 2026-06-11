import { Controller, useFormContext, useWatch } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

interface LightContextCardProps {
  maxInputLength: number;
}

export function LightContextCard({ maxInputLength }: LightContextCardProps) {
  const { t } = useTranslation();
  const { register, control } = useFormContext();

  const compactThresholdRatio = useWatch({
    control,
    name: "light_context_config.context_compact_config.compact_threshold_ratio",
  }) as number | undefined;
  const reserveThresholdRatio = useWatch({
    control,
    name: "light_context_config.context_compact_config.reserve_threshold_ratio",
  }) as number | undefined;

  const compactThreshold = Math.floor(
    (maxInputLength ?? 0) * (compactThresholdRatio ?? 0.8),
  );
  const reserveThreshold = Math.floor(
    (maxInputLength ?? 0) * (reserveThresholdRatio ?? 0.1),
  );

  return (
    <Card className={styles.formCard}>
      <CardHeader>
        <CardTitle>{t("agentConfig.lightContextTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label>{t("agentConfig.dialogPath")}</Label>
          <Input
            placeholder={t("agentConfig.dialogPathPlaceholder")}
            {...register("light_context_config.dialog_path")}
          />
        </div>

        <div className="space-y-1">
          <Label>{t("agentConfig.tokenCountEstimateDivisor")}</Label>
          <Controller
            name="light_context_config.token_count_estimate_divisor"
            control={control}
            rules={{
              required: t(
                "agentConfig.tokenCountEstimateDivisorRequired",
              ) as string,
            }}
            render={({ field }) => (
              <SliderWithValue
                value={field.value as number | undefined}
                min={2}
                max={5}
                step={0.25}
                marks={{ 2: "2", 3: "3", 4: "4", 5: "5" }}
                onChange={field.onChange}
              />
            )}
          />
        </div>

        <Accordion type="multiple">
          <AccordionItem value="contextCompact">
            <AccordionTrigger>
              {t("agentConfig.contextCompactCollapseLabel")}
            </AccordionTrigger>
            <AccordionContent className="space-y-4 pt-2">
              <div className="flex items-center space-x-2">
                <Controller
                  name="light_context_config.context_compact_config.enabled"
                  control={control}
                  render={({ field }) => (
                    <Switch
                      id="compact_enabled"
                      checked={Boolean(field.value)}
                      onCheckedChange={field.onChange}
                    />
                  )}
                />
                <Label htmlFor="compact_enabled">
                  {t("agentConfig.contextCompactEnabled")}
                </Label>
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.contextCompactRatio")}</Label>
                <Controller
                  name="light_context_config.context_compact_config.compact_threshold_ratio"
                  control={control}
                  rules={{
                    required: t(
                      "agentConfig.contextCompactRatioRequired",
                    ) as string,
                  }}
                  render={({ field }) => (
                    <SliderWithValue
                      value={field.value as number | undefined}
                      min={0.1}
                      max={0.9}
                      step={0.01}
                      marks={{ 0.1: "0.1", 0.5: "0.5", 0.9: "0.9" }}
                      onChange={field.onChange}
                    />
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.contextCompactThreshold")}</Label>
                <Input
                  disabled
                  value={
                    compactThreshold > 0
                      ? compactThreshold.toLocaleString()
                      : ""
                  }
                  placeholder={t(
                    "agentConfig.contextCompactThresholdPlaceholder",
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.contextCompactReserveRatio")}</Label>
                <Controller
                  name="light_context_config.context_compact_config.reserve_threshold_ratio"
                  control={control}
                  rules={{
                    required: t(
                      "agentConfig.contextCompactReserveRatioRequired",
                    ) as string,
                  }}
                  render={({ field }) => (
                    <SliderWithValue
                      value={field.value as number | undefined}
                      min={0}
                      max={0.3}
                      step={0.01}
                      marks={{ 0: "0", 0.15: "0.15", 0.3: "0.3" }}
                      onChange={field.onChange}
                    />
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.contextCompactReserveThreshold")}</Label>
                <Input
                  disabled
                  value={
                    reserveThreshold > 0
                      ? reserveThreshold.toLocaleString()
                      : ""
                  }
                  placeholder={t(
                    "agentConfig.contextCompactReserveThresholdPlaceholder",
                  )}
                />
              </div>

              <div className="flex items-center space-x-2">
                <Controller
                  name="light_context_config.context_compact_config.compact_with_thinking_block"
                  control={control}
                  render={({ field }) => (
                    <Switch
                      id="compact_thinking"
                      checked={Boolean(field.value)}
                      onCheckedChange={field.onChange}
                    />
                  )}
                />
                <Label htmlFor="compact_thinking">
                  {t("agentConfig.compactWithThinkingBlock")}
                </Label>
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="toolResultPruning">
            <AccordionTrigger>
              {t("agentConfig.toolResultPruningCollapseLabel")}
            </AccordionTrigger>
            <AccordionContent className="space-y-4 pt-2">
              <div className="flex items-center space-x-2">
                <Controller
                  name="light_context_config.tool_result_pruning_config.enabled"
                  control={control}
                  render={({ field }) => (
                    <Switch
                      id="pruning_enabled"
                      checked={Boolean(field.value)}
                      onCheckedChange={field.onChange}
                    />
                  )}
                />
                <Label htmlFor="pruning_enabled">
                  {t("agentConfig.toolResultCompactEnabled")}
                </Label>
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.toolResultCompactRecentN")}</Label>
                <Controller
                  name="light_context_config.tool_result_pruning_config.pruning_recent_n"
                  control={control}
                  rules={{
                    required: t(
                      "agentConfig.toolResultCompactRecentNRequired",
                    ) as string,
                  }}
                  render={({ field }) => (
                    <SliderWithValue
                      value={field.value as number | undefined}
                      min={1}
                      max={10}
                      step={1}
                      marks={{ 1: "1", 5: "5", 10: "10" }}
                      onChange={field.onChange}
                    />
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.toolResultCompactOldThreshold")}</Label>
                <Input
                  placeholder={t(
                    "agentConfig.toolResultCompactOldThresholdPlaceholder",
                  )}
                  {...register(
                    "light_context_config.tool_result_pruning_config.pruning_old_msg_max_bytes",
                    {
                      required: t(
                        "agentConfig.toolResultCompactOldThresholdRequired",
                      ) as string,
                    },
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>
                  {t("agentConfig.toolResultCompactRecentThreshold")}
                </Label>
                <Input
                  placeholder={t(
                    "agentConfig.toolResultCompactRecentThresholdPlaceholder",
                  )}
                  {...register(
                    "light_context_config.tool_result_pruning_config.pruning_recent_msg_max_bytes",
                    {
                      required: t(
                        "agentConfig.toolResultCompactRecentThresholdRequired",
                      ) as string,
                    },
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.toolResultCompactRetentionDays")}</Label>
                <Controller
                  name="light_context_config.tool_result_pruning_config.offload_retention_days"
                  control={control}
                  rules={{
                    required: t(
                      "agentConfig.toolResultCompactRetentionDaysRequired",
                    ) as string,
                  }}
                  render={({ field }) => (
                    <SliderWithValue
                      value={field.value as number | undefined}
                      min={1}
                      max={10}
                      step={1}
                      marks={{ 1: "1", 5: "5", 10: "10" }}
                      onChange={field.onChange}
                    />
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.exemptFileExtensions")}</Label>
                <Input
                  placeholder={t("agentConfig.exemptFileExtensionsPlaceholder")}
                  {...register(
                    "light_context_config.tool_result_pruning_config.exempt_file_extensions",
                  )}
                />
              </div>

              <div className="space-y-1">
                <Label>{t("agentConfig.exemptToolNames")}</Label>
                <Input
                  placeholder={t("agentConfig.exemptToolNamesPlaceholder")}
                  {...register(
                    "light_context_config.tool_result_pruning_config.exempt_tool_names",
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
