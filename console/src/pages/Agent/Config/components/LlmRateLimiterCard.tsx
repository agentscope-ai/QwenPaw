import { useFormContext } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export function LlmRateLimiterCard() {
  const { t } = useTranslation();
  const {
    register,
    getValues,
    formState: { errors },
  } = useFormContext();

  return (
    <Card className={styles.formCard}>
      <CardHeader>
        <CardTitle>{t("agentConfig.llmRateLimiterTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label>{t("agentConfig.llmMaxConcurrent")}</Label>
          <Input
            type="number"
            min={1}
            step={1}
            placeholder={t("agentConfig.llmMaxConcurrentPlaceholder")}
            {...register("llm_max_concurrent", {
              required: t("agentConfig.llmMaxConcurrentRequired") as string,
              min: {
                value: 1,
                message: t("agentConfig.llmMaxConcurrentRange") as string,
              },
              valueAsNumber: true,
            })}
          />
          {errors.llm_max_concurrent && (
            <p className="text-sm text-destructive">
              {errors.llm_max_concurrent.message as string}
            </p>
          )}
        </div>

        <div className="space-y-1">
          <Label>{t("agentConfig.llmMaxQpm")}</Label>
          <Input
            type="number"
            min={0}
            step={10}
            placeholder={t("agentConfig.llmMaxQpmPlaceholder")}
            {...register("llm_max_qpm", {
              required: t("agentConfig.llmMaxQpmRequired") as string,
              min: {
                value: 0,
                message: t("agentConfig.llmMaxQpmRange") as string,
              },
              valueAsNumber: true,
            })}
          />
          {errors.llm_max_qpm && (
            <p className="text-sm text-destructive">
              {errors.llm_max_qpm.message as string}
            </p>
          )}
        </div>

        <div className="space-y-1">
          <Label>{t("agentConfig.llmRateLimitPause")}</Label>
          <Input
            type="number"
            step={0.5}
            placeholder={t("agentConfig.llmRateLimitPausePlaceholder")}
            {...register("llm_rate_limit_pause", {
              required: t("agentConfig.llmRateLimitPauseRequired") as string,
              min: {
                value: 1.0,
                message: t("agentConfig.llmRateLimitPauseMin") as string,
              },
              valueAsNumber: true,
            })}
          />
          {errors.llm_rate_limit_pause && (
            <p className="text-sm text-destructive">
              {errors.llm_rate_limit_pause.message as string}
            </p>
          )}
        </div>

        <div className="space-y-1">
          <Label>{t("agentConfig.llmRateLimitJitter")}</Label>
          <Input
            type="number"
            step={0.5}
            placeholder={t("agentConfig.llmRateLimitJitterPlaceholder")}
            {...register("llm_rate_limit_jitter", {
              required: t("agentConfig.llmRateLimitJitterRequired") as string,
              min: {
                value: 0.0,
                message: t("agentConfig.llmRateLimitJitterMin") as string,
              },
              valueAsNumber: true,
            })}
          />
          {errors.llm_rate_limit_jitter && (
            <p className="text-sm text-destructive">
              {errors.llm_rate_limit_jitter.message as string}
            </p>
          )}
        </div>

        <div className="space-y-1">
          <Label>{t("agentConfig.llmAcquireTimeout")}</Label>
          <Input
            type="number"
            step={10}
            placeholder={t("agentConfig.llmAcquireTimeoutPlaceholder")}
            {...register("llm_acquire_timeout", {
              required: t("agentConfig.llmAcquireTimeoutRequired") as string,
              min: {
                value: 10.0,
                message: t("agentConfig.llmAcquireTimeoutMin") as string,
              },
              validate: (value: unknown) => {
                const pause = getValues("llm_rate_limit_pause") as number;
                const jitter = getValues("llm_rate_limit_jitter") as number;
                const v = value as number;
                if (
                  typeof v !== "number" ||
                  typeof pause !== "number" ||
                  typeof jitter !== "number" ||
                  v > pause + jitter
                ) {
                  return true;
                }
                return t(
                  "agentConfig.llmAcquireTimeoutGtPauseJitter",
                ) as string;
              },
              valueAsNumber: true,
            })}
          />
          {errors.llm_acquire_timeout && (
            <p className="text-sm text-destructive">
              {errors.llm_acquire_timeout.message as string}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
