import { useEffect, useState } from "react";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import type { HeartbeatConfig } from "../../../api/types/heartbeat";
import { parseEvery, serializeEvery, type EveryUnit } from "./parseEvery";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { useAppMessage } from "../../../hooks/useAppMessage";

dayjs.extend(customParseFormat);

type HeartbeatFormValues = Omit<HeartbeatConfig, "every"> & {
  everyNumber?: number;
  everyUnit?: EveryUnit;
  useActiveHours?: boolean;
  activeHoursStart?: string;
  activeHoursEnd?: string;
};

const TARGET_OPTIONS = [
  { value: "main", labelKey: "heartbeat.targetMain" },
  { value: "last", labelKey: "heartbeat.targetLast" },
  { value: "inbox", labelKey: "heartbeat.targetInbox" },
];

const EVERY_UNIT_OPTIONS: { value: EveryUnit; labelKey: string }[] = [
  { value: "m", labelKey: "heartbeat.unitMinutes" },
  { value: "h", labelKey: "heartbeat.unitHours" },
];

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5 mb-4">
      <Label>
        {required && <span className="text-destructive mr-1">*</span>}
        {label}
      </Label>
      {children}
    </div>
  );
}

function HeartbeatPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { message } = useAppMessage();

  const [values, setValues] = useState<HeartbeatFormValues>({
    enabled: false,
    everyNumber: 6,
    everyUnit: "h",
    target: "main",
    useActiveHours: false,
    activeHoursStart: "08:00",
    activeHoursEnd: "22:00",
  });

  const set = <K extends keyof HeartbeatFormValues>(
    key: K,
    value: HeartbeatFormValues[K],
  ) => setValues((prev) => ({ ...prev, [key]: value }));

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const data = await api.getHeartbeatConfig();
      const everyParts = parseEvery(data.every ?? "6h");
      setValues({
        enabled: data.enabled ?? false,
        everyNumber: everyParts.number,
        everyUnit: everyParts.unit,
        target: data.target ?? "main",
        useActiveHours: !!data.activeHours,
        activeHoursStart: data.activeHours?.start ?? "08:00",
        activeHoursEnd: data.activeHours?.end ?? "22:00",
      });
    } catch (e) {
      console.error("Failed to load heartbeat config:", e);
      message.error(t("heartbeat.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const every =
      values.everyNumber != null && values.everyUnit
        ? serializeEvery({ number: values.everyNumber, unit: values.everyUnit })
        : "6h";
    const body: HeartbeatConfig = {
      enabled: values.enabled ?? false,
      every,
      target: values.target ?? "main",
      activeHours:
        values.useActiveHours &&
        values.activeHoursStart &&
        values.activeHoursEnd
          ? { start: values.activeHoursStart, end: values.activeHoursEnd }
          : undefined,
    };
    setSaving(true);
    try {
      await api.updateHeartbeatConfig(body);
      message.success(t("heartbeat.saveSuccess"));
    } catch (e) {
      console.error("Failed to save heartbeat config:", e);
      message.error(t("heartbeat.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <PageHeader
          items={[{ title: t("nav.control") }, { title: t("heartbeat.title") }]}
        />
        <div className="flex items-center justify-center h-32">
          <Loader2 className="animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("heartbeat.title") }]}
      />

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <Card className="max-w-[520px]">
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit}>
              <Field label={t("heartbeat.enabled")}>
                <Switch
                  checked={Boolean(values.enabled)}
                  onCheckedChange={(checked) => set("enabled", checked)}
                />
              </Field>

              <Field label={t("heartbeat.every")} required>
                <div className="flex gap-2">
                  <Input
                    type="number"
                    min={1}
                    value={values.everyNumber ?? ""}
                    onChange={(e) =>
                      set("everyNumber", Number(e.target.value) || 1)
                    }
                    className="w-24"
                  />
                  <Select
                    value={values.everyUnit ?? "h"}
                    onValueChange={(v) => set("everyUnit", v as EveryUnit)}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EVERY_UNIT_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {t(opt.labelKey)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </Field>

              <Field label={t("heartbeat.target")}>
                <Select
                  value={values.target ?? "main"}
                  onValueChange={(v) => set("target", v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TARGET_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {t(opt.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field label={t("heartbeat.activeHours")}>
                <Switch
                  checked={Boolean(values.useActiveHours)}
                  onCheckedChange={(checked) => set("useActiveHours", checked)}
                />
              </Field>

              {values.useActiveHours && (
                <div className="flex gap-4">
                  <Field label={t("heartbeat.activeStart")}>
                    <input
                      type="time"
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                      value={values.activeHoursStart ?? "08:00"}
                      step={900}
                      onChange={(e) => set("activeHoursStart", e.target.value)}
                    />
                  </Field>
                  <Field label={t("heartbeat.activeEnd")}>
                    <input
                      type="time"
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                      value={values.activeHoursEnd ?? "22:00"}
                      step={900}
                      onChange={(e) => set("activeHoursEnd", e.target.value)}
                    />
                  </Field>
                </div>
              )}

              <div className="mt-4">
                <Button type="submit" disabled={saving}>
                  {saving && (
                    <Loader2 size={14} className="animate-spin mr-2" />
                  )}
                  {t("common.save")}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default HeartbeatPage;
