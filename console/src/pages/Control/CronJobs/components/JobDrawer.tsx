import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  CronDispatchTargetItem,
  CronJobSpecOutput,
} from "../../../../api/types";
import { DEFAULT_FORM_VALUES } from "./constants";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2 } from "lucide-react";

type CronJob = CronJobSpecOutput;
type SelectOption = { value: string; label: string };

interface JobDrawerProps {
  open: boolean;
  editingJob: CronJob | null;
  form: {
    getFieldValue: (name: string) => any;
    setFieldsValue: (values: Record<string, any>) => void;
    resetFields: () => void;
    submit: () => void;
  };
  saving: boolean;
  targetItems: CronDispatchTargetItem[];
  targetChannels: string[];
  onReloadTargets: () => Promise<void>;
  onClose: () => void;
  onSubmit: (values: any) => void;
}

type FormValues = Record<string, any>;

// FormField: a labeled input row
function Field({
  label,
  required,
  tooltip,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  tooltip?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5 mb-4">
      <Label>
        {required && <span className="text-destructive mr-1">*</span>}
        {label}
        {tooltip && (
          <span className="text-muted-foreground text-xs ml-1" title={tooltip}>
            (?)
          </span>
        )}
      </Label>
      {children}
      {error && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}

export function JobDrawer({
  open,
  editingJob,
  form,
  saving,
  targetItems,
  targetChannels,
  onReloadTargets,
  onClose,
  onSubmit,
}: JobDrawerProps) {
  const { t } = useTranslation();
  const timezoneOptions = useTimezoneOptions();
  const [saveInboxTouched, setSaveInboxTouched] = useState(false);
  const [channelSearch, setChannelSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");

  // Local form state — mirrors antd Form values
  const [values, setValues] = useState<FormValues>({
    ...DEFAULT_FORM_VALUES,
    "schedule.timezone": "UTC",
    scheduleType: "cron",
    cronType: "daily",
    "dispatch.channel": "console",
    "dispatch.type": "channel",
    "dispatch.mode": "final",
  });

  const get = (key: string) => {
    // support dotted keys like "dispatch.channel"
    if (key in values) return values[key];
    const parts = key.split(".");
    let obj: any = values;
    for (const p of parts) {
      if (obj == null) return undefined;
      obj = obj[p];
    }
    return obj;
  };

  const set = (key: string, value: any) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  // Override form proxy to sync with local state
  useEffect(() => {
    // Expose form API via ref so parent can call setFieldsValue
    form.getFieldValue = get;
    form.setFieldsValue = (v: Record<string, any>) => {
      setValues((prev) => ({ ...prev, ...flattenValues(v) }));
    };
    form.resetFields = () => {
      setValues(flattenValues(DEFAULT_FORM_VALUES));
    };
    form.submit = handleSubmit;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);

  function flattenValues(
    obj: Record<string, any>,
    prefix = "",
  ): Record<string, any> {
    const result: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (
        v !== null &&
        typeof v === "object" &&
        !Array.isArray(v) &&
        !(v instanceof Date)
      ) {
        Object.assign(result, flattenValues(v, key));
      } else {
        result[key] = v;
      }
    }
    return result;
  }

  useEffect(() => {
    if (open) {
      setSaveInboxTouched(false);
      setChannelSearch("");
      setUserSearch("");
      setSessionSearch("");
      onReloadTargets().catch((err) =>
        console.error("Failed to reload cron dispatch targets", err),
      );
    }
  }, [open, editingJob?.id, onReloadTargets]);

  const mergeOptions = (
    vals: Iterable<string>,
    selected?: string,
    search?: string,
  ): SelectOption[] => {
    const merged = new Set<string>();
    Array.from(vals).forEach((v) => {
      if (v?.trim()) merged.add(v.trim());
    });
    if (selected?.trim()) merged.add(selected.trim());
    if (search?.trim()) merged.add(search.trim());
    return [...merged].sort().map((v) => ({ value: v, label: v }));
  };

  const selectedChannel = values["dispatch.channel"];
  const selectedTargetUserId = values["dispatch.target.user_id"];

  const channelOptions = useMemo(
    () => mergeOptions(targetChannels, selectedChannel, channelSearch),
    [channelSearch, selectedChannel, targetChannels],
  );

  const userOptions = useMemo(() => {
    const opts = new Set<string>();
    targetItems.forEach((item) => {
      if (!selectedChannel || item.channel === selectedChannel) {
        opts.add(item.user_id);
      }
    });
    return mergeOptions(opts, selectedTargetUserId, userSearch);
  }, [targetItems, selectedChannel, selectedTargetUserId, userSearch]);

  const sessionOptions = useMemo(() => {
    const opts = new Set<string>();
    targetItems.forEach((item) => {
      if (
        (!selectedChannel || item.channel === selectedChannel) &&
        (!selectedTargetUserId || item.user_id === selectedTargetUserId)
      ) {
        opts.add(item.session_id);
      }
    });
    return mergeOptions(
      opts,
      values["dispatch.target.session_id"],
      sessionSearch,
    );
  }, [
    targetItems,
    selectedChannel,
    selectedTargetUserId,
    sessionSearch,
    values,
  ]);

  const scheduleType = values["scheduleType"] || "cron";
  const cronType = values["cronType"] || "daily";
  const taskType = values["task_type"] || "agent";
  const onceRepeatEnabled = Boolean(values["onceRepeatEnabled"]);
  const repeatEndType = values["onceRepeatEndType"] || "never";
  const isEdit = !!editingJob;

  function handleSubmit() {
    // Auto-update save_result_to_inbox default
    const finalValues = { ...values };
    if (!isEdit && !saveInboxTouched) {
      const textType = taskType === "text";
      const cronSched = scheduleType === "cron";
      finalValues["save_result_to_inbox"] = !(textType && cronSched);
    }
    onSubmit(unflattenValues(finalValues));
  }

  function unflattenValues(flat: Record<string, any>): Record<string, any> {
    const result: Record<string, any> = {};
    for (const [k, v] of Object.entries(flat)) {
      const parts = k.split(".");
      let obj = result;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!obj[parts[i]] || typeof obj[parts[i]] !== "object") {
          obj[parts[i]] = {};
        }
        obj = obj[parts[i]];
      }
      obj[parts[parts.length - 1]] = v;
    }
    return result;
  }

  const DAYS_OF_WEEK = [
    { value: "mon", labelKey: "cronJobs.cronDayMon" },
    { value: "tue", labelKey: "cronJobs.cronDayTue" },
    { value: "wed", labelKey: "cronJobs.cronDayWed" },
    { value: "thu", labelKey: "cronJobs.cronDayThu" },
    { value: "fri", labelKey: "cronJobs.cronDayFri" },
    { value: "sat", labelKey: "cronJobs.cronDaySat" },
    { value: "sun", labelKey: "cronJobs.cronDaySun" },
  ];

  const selectedDays: string[] = values["cronDaysOfWeek"] || [];

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[600px] flex flex-col p-0">
        <SheetHeader className="px-6 py-4 border-b">
          <SheetTitle>
            {editingJob ? t("cronJobs.editJob") : t("cronJobs.createJob")}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {editingJob ? t("cronJobs.editJob") : t("cronJobs.createJob")}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {isEdit && (
            <Field label={t("cronJobs.id")} tooltip={t("cronJobs.idTooltip")}>
              <Input
                disabled
                value={values["id"] || ""}
                placeholder={t("cronJobs.jobIdPlaceholder")}
              />
            </Field>
          )}

          <Field
            label={t("cronJobs.name")}
            required
            tooltip={t("cronJobs.nameTooltip")}
          >
            <Input
              value={values["name"] || ""}
              onChange={(e) => set("name", e.target.value)}
              placeholder={t("cronJobs.jobNamePlaceholder")}
            />
          </Field>

          <Field label={t("cronJobs.enabled")}>
            <Switch
              checked={Boolean(values["enabled"])}
              onCheckedChange={(v) => set("enabled", v)}
            />
          </Field>

          <Field
            label={t("cronJobs.saveResultToInbox")}
            tooltip={t("cronJobs.saveResultToInboxTooltip")}
          >
            <Switch
              checked={Boolean(values["save_result_to_inbox"])}
              onCheckedChange={(v) => {
                setSaveInboxTouched(true);
                set("save_result_to_inbox", v);
              }}
            />
          </Field>

          <Field label={t("cronJobs.scheduleType")} required>
            <Select
              value={scheduleType}
              onValueChange={(v) => set("scheduleType", v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cron">
                  {t("cronJobs.scheduleTypeRecurring")}
                </SelectItem>
                <SelectItem value="once">
                  {t("cronJobs.scheduleTypeOnce")}
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>

          {scheduleType === "once" && (
            <>
              <Field label={t("cronJobs.onceRunAt")} required>
                <Input
                  type="datetime-local"
                  value={values["onceRunAt"] || ""}
                  onChange={(e) => set("onceRunAt", e.target.value)}
                />
              </Field>
              <Field
                label={t("cronJobs.repeatEnabled")}
                tooltip={t("cronJobs.repeatEnabledTooltip")}
              >
                <Switch
                  checked={onceRepeatEnabled}
                  onCheckedChange={(v) => set("onceRepeatEnabled", v)}
                />
              </Field>
            </>
          )}

          {scheduleType === "once" && onceRepeatEnabled && (
            <>
              <Field label={t("cronJobs.repeatFrequency")}>
                <div className="flex items-center gap-2">
                  <span className="text-sm">
                    {t("cronJobs.repeatEveryPrefix")}
                  </span>
                  <Input
                    type="number"
                    min={1}
                    className="w-24"
                    value={values["onceRepeatEveryDays"] || 1}
                    onChange={(e) =>
                      set("onceRepeatEveryDays", Number(e.target.value))
                    }
                  />
                  <span className="text-sm">
                    {t("cronJobs.repeatEverySuffix")}
                  </span>
                </div>
              </Field>
              <Field label={t("cronJobs.repeatEndType")} required>
                <Select
                  value={repeatEndType}
                  onValueChange={(v) => set("onceRepeatEndType", v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="never">
                      {t("cronJobs.repeatEndNever")}
                    </SelectItem>
                    <SelectItem value="until">
                      {t("cronJobs.repeatEndUntil")}
                    </SelectItem>
                    <SelectItem value="count">
                      {t("cronJobs.repeatEndCount")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              {repeatEndType === "until" && (
                <Field label={t("cronJobs.repeatUntil")} required>
                  <Input
                    type="datetime-local"
                    value={values["onceRepeatUntil"] || ""}
                    onChange={(e) => set("onceRepeatUntil", e.target.value)}
                  />
                </Field>
              )}
              {repeatEndType === "count" && (
                <Field label={t("cronJobs.repeatCount")} required>
                  <Input
                    type="number"
                    min={1}
                    value={values["onceRepeatCount"] || 2}
                    onChange={(e) =>
                      set("onceRepeatCount", Number(e.target.value))
                    }
                  />
                </Field>
              )}
            </>
          )}

          {scheduleType === "cron" && (
            <>
              <Field
                label={t("cronJobs.scheduleCronLabel")}
                required
                tooltip={t("cronJobs.cronTooltip")}
              >
                <Select
                  value={cronType}
                  onValueChange={(v) => set("cronType", v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hourly">
                      {t("cronJobs.cronTypeHourly")}
                    </SelectItem>
                    <SelectItem value="daily">
                      {t("cronJobs.cronTypeDaily")}
                    </SelectItem>
                    <SelectItem value="weekly">
                      {t("cronJobs.cronTypeWeekly")}
                    </SelectItem>
                    <SelectItem value="custom">
                      {t("cronJobs.cronTypeCustom")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              {(cronType === "daily" || cronType === "weekly") && (
                <Field label={t("cronJobs.cronTime")}>
                  <Input
                    type="time"
                    value={values["cronTime"] || "09:00"}
                    onChange={(e) => set("cronTime", e.target.value)}
                  />
                </Field>
              )}

              {cronType === "weekly" && (
                <Field label={t("cronJobs.cronDaysOfWeek")}>
                  <div className="flex flex-wrap gap-3">
                    {DAYS_OF_WEEK.map(({ value, labelKey }) => {
                      const checked = selectedDays.includes(value);
                      const checkId = `dow-${value}`;
                      return (
                        <div key={value} className="flex items-center gap-1.5">
                          <Checkbox
                            id={checkId}
                            checked={checked}
                            onCheckedChange={() => {
                              const next = checked
                                ? selectedDays.filter((d) => d !== value)
                                : [...selectedDays, value];
                              set("cronDaysOfWeek", next);
                            }}
                          />
                          <Label
                            htmlFor={checkId}
                            className="font-normal cursor-pointer"
                          >
                            {t(labelKey)}
                          </Label>
                        </div>
                      );
                    })}
                  </div>
                </Field>
              )}

              {cronType === "custom" && (
                <Field label={t("cronJobs.cronCustomExpression")} required>
                  <Input
                    placeholder="0 9 * * *"
                    value={values["cronCustom"] || ""}
                    onChange={(e) => set("cronCustom", e.target.value)}
                  />
                  <div className="text-xs text-muted-foreground mt-1 space-y-1">
                    <div>{t("cronJobs.cronExample")}</div>
                    <div>
                      {t("cronJobs.cronHelper")}{" "}
                      <a
                        href="https://crontab.guru/"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary underline"
                      >
                        {t("cronJobs.cronHelperLink")} →
                      </a>
                    </div>
                  </div>
                </Field>
              )}
            </>
          )}

          <Field
            label={t("cronJobs.scheduleTimezone")}
            tooltip={t("cronJobs.timezoneTooltip")}
          >
            <Select
              value={values["schedule.timezone"] || "UTC"}
              onValueChange={(v) => set("schedule.timezone", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t("cronJobs.selectTimezone")} />
              </SelectTrigger>
              <SelectContent className="max-h-60">
                {timezoneOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t("cronJobs.taskType")}
            required
            tooltip={t("cronJobs.taskTypeTooltip")}
          >
            <Select value={taskType} onValueChange={(v) => set("task_type", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text">text</SelectItem>
                <SelectItem value="agent">agent</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t("cronJobs.text")}
            required={taskType === "text"}
            tooltip={t("cronJobs.textTooltip")}
          >
            <Textarea
              rows={3}
              placeholder={t("cronJobs.taskDescriptionPlaceholder")}
              value={values["text"] || ""}
              onChange={(e) => set("text", e.target.value)}
            />
          </Field>

          <Field
            label={t("cronJobs.requestInput")}
            required={taskType === "agent"}
            tooltip={t("cronJobs.requestInputTooltip")}
          >
            <Textarea
              rows={6}
              placeholder='[{"role":"user","content":[{"text":"Hello","type":"text"}]}]'
              value={values["request.input"] || ""}
              onChange={(e) => set("request.input", e.target.value)}
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground mt-1">
              {t("cronJobs.requestInputExample")}
            </p>
          </Field>

          <Field
            label={t("cronJobs.dispatchChannel")}
            required
            tooltip={t("cronJobs.dispatchChannelTooltip")}
          >
            <Select
              value={selectedChannel || ""}
              onValueChange={(v) => set("dispatch.channel", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="console" />
              </SelectTrigger>
              <SelectContent>
                {channelOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t("cronJobs.dispatchTargetUserId")}
            required
            tooltip={t("cronJobs.dispatchTargetUserIdTooltip")}
          >
            <Select
              value={selectedTargetUserId || ""}
              onValueChange={(v) => set("dispatch.target.user_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="admin" />
              </SelectTrigger>
              <SelectContent>
                {userOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t("cronJobs.dispatchTargetSessionId")}
            required
            tooltip={t("cronJobs.dispatchTargetSessionIdTooltip")}
          >
            <Select
              value={values["dispatch.target.session_id"] || ""}
              onValueChange={(v) => set("dispatch.target.session_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="default" />
              </SelectTrigger>
              <SelectContent>
                {sessionOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t("cronJobs.dispatchMode")}
            tooltip={t("cronJobs.dispatchModeTooltip")}
          >
            <Select
              value={values["dispatch.mode"] || "final"}
              onValueChange={(v) => set("dispatch.mode", v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stream">stream</SelectItem>
                <SelectItem value="final">final</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field
            label={t("cronJobs.runtimeShareSession")}
            tooltip={t("cronJobs.shareSessionTooltip")}
          >
            <Switch
              checked={values["runtime.share_session"] !== false}
              onCheckedChange={(v) => set("runtime.share_session", v)}
            />
          </Field>

          <Field
            label={t("cronJobs.runtimeMaxConcurrency")}
            tooltip={t("cronJobs.maxConcurrencyTooltip")}
          >
            <Input
              type="number"
              min={1}
              placeholder="1"
              value={values["runtime.max_concurrency"] ?? ""}
              onChange={(e) =>
                set(
                  "runtime.max_concurrency",
                  e.target.value ? Number(e.target.value) : undefined,
                )
              }
            />
          </Field>

          <Field
            label={t("cronJobs.runtimeTimeoutSeconds")}
            tooltip={t("cronJobs.timeoutSecondsTooltip")}
          >
            <Input
              type="number"
              min={1}
              placeholder="300"
              value={values["runtime.timeout_seconds"] ?? ""}
              onChange={(e) =>
                set(
                  "runtime.timeout_seconds",
                  e.target.value ? Number(e.target.value) : undefined,
                )
              }
            />
          </Field>

          <Field
            label={t("cronJobs.runtimeMisfireGraceSeconds")}
            tooltip={t("cronJobs.misfireGraceSecondsTooltip")}
          >
            <Input
              type="number"
              min={0}
              placeholder="60"
              value={values["runtime.misfire_grace_seconds"] ?? ""}
              onChange={(e) =>
                set(
                  "runtime.misfire_grace_seconds",
                  e.target.value ? Number(e.target.value) : undefined,
                )
              }
            />
          </Field>
        </div>

        <SheetFooter className="px-6 py-4 border-t flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin mr-2" />}
            {t("common.save")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
