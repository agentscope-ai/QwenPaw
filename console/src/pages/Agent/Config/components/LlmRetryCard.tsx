import { Controller, useFormContext } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface LlmRetryCardProps {
  llmRetryEnabled?: boolean;
}

export function LlmRetryCard({ llmRetryEnabled = true }: LlmRetryCardProps) {
  const { t } = useTranslation();
  const {
    register,
    control,
    getValues,
    formState: { errors },
  } = useFormContext();

  return (
    <Card className={styles.formCard}>
      <CardHeader>
        <CardTitle>{t("agentConfig.llmRetryTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center space-x-2">
          <Controller
            name="llm_retry_enabled"
            control={control}
            render={({ field }) => (
              <Switch
                id="llm_retry_enabled"
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
          <Label htmlFor="llm_retry_enabled">
            {t("agentConfig.llmRetryEnabled")}
          </Label>
        </div>

        <div className={styles.llmRetryRow}>
          <div className={styles.llmRetryField + " space-y-1"}>
            <Label>{t("agentConfig.llmMaxRetries")}</Label>
            <Input
              type="number"
              min={1}
              step={1}
              disabled={!llmRetryEnabled}
              placeholder={t("agentConfig.llmMaxRetriesPlaceholder")}
              {...register("llm_max_retries", {
                required: t("agentConfig.llmMaxRetriesRequired") as string,
                min: {
                  value: 1,
                  message: t("agentConfig.llmMaxRetriesMin") as string,
                },
                valueAsNumber: true,
              })}
            />
            {errors.llm_max_retries && (
              <p className="text-sm text-destructive">
                {errors.llm_max_retries.message as string}
              </p>
            )}
          </div>

          <div className={styles.llmRetryField + " space-y-1"}>
            <Label>{t("agentConfig.llmBackoffBase")}</Label>
            <Input
              type="number"
              step={0.1}
              disabled={!llmRetryEnabled}
              placeholder={t("agentConfig.llmBackoffBasePlaceholder")}
              {...register("llm_backoff_base", {
                required: t("agentConfig.llmBackoffBaseRequired") as string,
                min: {
                  value: 0.1,
                  message: t("agentConfig.llmBackoffBaseMin") as string,
                },
                valueAsNumber: true,
              })}
            />
            {errors.llm_backoff_base && (
              <p className="text-sm text-destructive">
                {errors.llm_backoff_base.message as string}
              </p>
            )}
          </div>

          <div className={styles.llmRetryField + " space-y-1"}>
            <Label>{t("agentConfig.llmBackoffCap")}</Label>
            <Input
              type="number"
              step={0.5}
              disabled={!llmRetryEnabled}
              placeholder={t("agentConfig.llmBackoffCapPlaceholder")}
              {...register("llm_backoff_cap", {
                required: t("agentConfig.llmBackoffCapRequired") as string,
                min: {
                  value: 0.5,
                  message: t("agentConfig.llmBackoffCapMin") as string,
                },
                validate: (value: unknown) => {
                  const backoffBase = getValues("llm_backoff_base") as number;
                  const v = value as number;
                  if (
                    typeof v !== "number" ||
                    typeof backoffBase !== "number" ||
                    v >= backoffBase
                  ) {
                    return true;
                  }
                  return t("agentConfig.llmBackoffCapGteBase") as string;
                },
                valueAsNumber: true,
              })}
            />
            {errors.llm_backoff_cap && (
              <p className="text-sm text-destructive">
                {errors.llm_backoff_cap.message as string}
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
