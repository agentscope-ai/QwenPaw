import { useCallback, useEffect, useState } from "react";
import { Controller, useFormContext } from "react-hook-form";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import { planApi } from "../../../../api/modules/plan";
import { useAgentStore } from "../../../../stores/agentStore";
import {
  CONTEXT_MANAGER_BACKEND_OPTIONS,
  MEMORY_MANAGER_BACKEND_OPTIONS,
} from "../../../../constants/backendMappings";
import styles from "../index.module.less";

const LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "id", label: "Bahasa Indonesia" },
  { value: "ru", label: "Русский" },
];

interface ReactAgentCardProps {
  language: string;
  savingLang: boolean;
  onLanguageChange: (value: string) => void;
  timezone: string;
  savingTimezone: boolean;
  onTimezoneChange: (value: string) => void;
}

export function ReactAgentCard({
  language,
  savingLang,
  onLanguageChange,
  timezone,
  savingTimezone,
  onTimezoneChange,
}: ReactAgentCardProps) {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const {
    control,
    register,
    formState: { errors },
  } = useFormContext();
  const [planEnabled, setPlanEnabled] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const timezoneOptions = useTimezoneOptions();

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig()
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  const handlePlanToggle = useCallback(
    async (checked: boolean) => {
      setPlanLoading(true);
      const prev = planEnabled;
      setPlanEnabled(checked);
      try {
        const res = await planApi.updatePlanConfig({ enabled: checked });
        setPlanEnabled(res.enabled);
      } catch {
        setPlanEnabled(prev);
      } finally {
        setPlanLoading(false);
      }
    },
    [planEnabled],
  );

  return (
    <Card className={styles.formCard}>
      <CardHeader>
        <CardTitle>{t("agentConfig.reactAgentTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className={styles.reactAgentRow}>
          {/* Language */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.language")}</Label>
            <Select
              value={language}
              onValueChange={onLanguageChange}
              disabled={savingLang}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANGUAGE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Timezone */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.timezone")}</Label>
            <Select
              value={timezone}
              onValueChange={onTimezoneChange}
              disabled={savingTimezone}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t("agentConfig.selectTimezone")} />
              </SelectTrigger>
              <SelectContent>
                {timezoneOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label as string}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Max Iters */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.maxIters")}</Label>
            <Input
              type="number"
              min={1}
              placeholder={t("agentConfig.maxItersPlaceholder")}
              {...register("max_iters", {
                required: t("agentConfig.maxItersRequired") as string,
                min: {
                  value: 1,
                  message: t("agentConfig.maxItersMin") as string,
                },
                valueAsNumber: true,
              })}
            />
            {errors.max_iters && (
              <p className="text-sm text-destructive">
                {errors.max_iters.message as string}
              </p>
            )}
          </div>

          {/* Shell timeout */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.shellCommandTimeout")}</Label>
            <Input
              type="number"
              min={1}
              step={10}
              placeholder={t("agentConfig.shellCommandTimeoutPlaceholder")}
              {...register("shell_command_timeout", {
                required: t(
                  "agentConfig.shellCommandTimeoutRequired",
                ) as string,
                min: {
                  value: 1,
                  message: t("agentConfig.shellCommandTimeoutMin") as string,
                },
                valueAsNumber: true,
              })}
            />
            {errors.shell_command_timeout && (
              <p className="text-sm text-destructive">
                {errors.shell_command_timeout.message as string}
              </p>
            )}
          </div>

          {/* Shell executable */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.shellCommandExecutable")}</Label>
            <Input
              placeholder={t("agentConfig.shellCommandExecutablePlaceholder")}
              {...register("shell_command_executable")}
            />
          </div>
        </div>

        {/* Auto-continue switch */}
        <div className="flex items-center space-x-2">
          <Controller
            name="auto_continue_on_text_only"
            control={control}
            render={({ field }) => (
              <Switch
                id="auto_continue"
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
          <Label htmlFor="auto_continue">
            {t("agentConfig.autoContinueOnTextOnly")}
          </Label>
        </div>

        {/* Auto-title switch */}
        <div className="flex items-center space-x-2">
          <Controller
            name="auto_title_config.enabled"
            control={control}
            render={({ field }) => (
              <Switch
                id="auto_title"
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
          <Label htmlFor="auto_title">
            {t("agentConfig.autoGenerateSessionTitle")}
          </Label>
        </div>

        <div className={styles.reactAgentRow}>
          {/* Context backend */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.contextManagerBackend")}</Label>
            <Controller
              name="context_manager_backend"
              control={control}
              render={({ field }) => (
                <Select
                  value={field.value as string}
                  onValueChange={field.onChange}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CONTEXT_MANAGER_BACKEND_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label as string}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          {/* Memory backend */}
          <div className={styles.reactAgentField + " space-y-1"}>
            <Label>{t("agentConfig.memoryManagerBackend")}</Label>
            <Controller
              name="memory_manager_backend"
              control={control}
              render={({ field }) => (
                <Select
                  value={field.value as string}
                  onValueChange={field.onChange}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MEMORY_MANAGER_BACKEND_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label as string}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>

        <div className="flex items-center gap-2 p-3 rounded-md bg-yellow-50 dark:bg-yellow-950/30 text-yellow-700 dark:text-yellow-300 text-sm">
          <AlertTriangle size={16} className="shrink-0" />
          <span>{t("agentConfig.backendRestartWarning")}</span>
        </div>

        {/* Plan mode */}
        <div className="flex items-center space-x-2">
          <Switch
            id="plan_mode"
            checked={planEnabled}
            disabled={planLoading}
            onCheckedChange={handlePlanToggle}
          />
          <Label htmlFor="plan_mode">
            {t("agentConfig.planMode", "Plan Mode")}
          </Label>
        </div>
      </CardContent>
    </Card>
  );
}
