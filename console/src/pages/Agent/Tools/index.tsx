import { useEffect, useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import api from "../../../api";
import { Eye, EyeOff, Zap, Clock, Settings, Loader2 } from "lucide-react";
import { useTools } from "./useTools";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";
import { PageHeader } from "@/components/PageHeader";
import { Controller, useForm } from "react-hook-form";
import styles from "./index.module.less";

const ICON_PALETTE = [
  "#f56a00",
  "#7265e6",
  "#ffbf00",
  "#00a2ae",
  "#87d068",
  "#1890ff",
  "#eb2f96",
  "#722ed1",
];

function hashStringToIndex(value: string, mod: number): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % mod;
}

function ToolIcon({ icon, name }: { icon: string; name: string }) {
  if (icon) {
    return <span>{icon}</span>;
  }
  const letter = name.charAt(0).toUpperCase();
  const backgroundColor =
    ICON_PALETTE[hashStringToIndex(name, ICON_PALETTE.length)];
  return (
    <span className={styles.toolIconFallback} style={{ backgroundColor }}>
      {letter}
    </span>
  );
}

function ToolConfigModal({
  tool,
  visible,
  onClose,
  onSave,
}: {
  tool: ToolInfo;
  visible: boolean;
  onClose: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}) {
  const form = useForm<Record<string, unknown>>();
  const [saving, setSaving] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const { t } = useTranslation();

  useEffect(() => {
    if (!visible || !tool) return;
    form.reset({});
    setLoadingConfig(true);
    let cancelled = false;
    api
      .getToolConfig(tool.name)
      .then((config) => {
        if (!cancelled) form.reset(config || {});
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, tool.name, form]);

  const handleSave = form.handleSubmit(async (values) => {
    setSaving(true);
    try {
      await onSave(values);
      onClose();
    } catch (error) {
      console.error("Failed to save config:", error);
    } finally {
      setSaving(false);
    }
  });

  const renderField = (
    field: import("../../../api/modules/tools").ToolConfigField,
  ) => {
    switch (field.type) {
      case "password":
        return (
          <Input
            type="password"
            placeholder={field.placeholder}
            autoComplete="off"
            {...form.register(field.name)}
          />
        );

      case "number":
        return (
          <Input
            type="number"
            placeholder={field.placeholder}
            min={field.min}
            max={field.max}
            {...form.register(field.name, { valueAsNumber: true })}
          />
        );

      case "boolean":
        return (
          <Controller
            control={form.control}
            name={field.name}
            render={({ field: f }) => (
              <Switch checked={Boolean(f.value)} onCheckedChange={f.onChange} />
            )}
          />
        );

      case "select":
        return (
          <Controller
            control={form.control}
            name={field.name}
            render={({ field: f }) => (
              <Select value={String(f.value || "")} onValueChange={f.onChange}>
                <SelectTrigger>
                  <SelectValue placeholder={field.placeholder} />
                </SelectTrigger>
                <SelectContent>
                  {field.options?.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        );

      case "textarea":
        return (
          <Textarea
            placeholder={field.placeholder}
            rows={4}
            {...form.register(field.name)}
          />
        );

      case "text":
      default:
        return (
          <Input
            placeholder={field.placeholder}
            {...form.register(field.name)}
          />
        );
    }
  };

  return (
    <Dialog open={visible} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{`${t("tools.configure")} - ${tool.name}`}</DialogTitle>
        </DialogHeader>
        {loadingConfig ? (
          <div className="flex justify-center py-8">
            <Loader2 className="animate-spin" />
          </div>
        ) : (
          <form
            id="tool-config-form"
            onSubmit={handleSave}
            className="space-y-4"
          >
            {tool.config_fields?.map((field) => (
              <div key={field.name} className="space-y-1">
                <Label>{field.label}</Label>
                {renderField(field)}
                {field.help && (
                  <p className="text-xs text-muted-foreground">{field.help}</p>
                )}
              </div>
            ))}
          </form>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            form="tool-config-form"
            disabled={saving || loadingConfig}
          >
            {saving && <Loader2 size={14} className="animate-spin mr-1" />}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function ToolsPage() {
  const { t } = useTranslation();
  const {
    tools,
    loading,
    batchLoading,
    toggleEnabled,
    toggleAsyncExecution,
    enableAll,
    disableAll,
    loadTools,
    saveToolConfig,
  } = useTools();
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [currentTool, setCurrentTool] = useState<ToolInfo | null>(null);

  const handleToggle = (tool: ToolInfo) => {
    toggleEnabled(tool);
  };

  const handleConfigure = (tool: ToolInfo) => {
    setCurrentTool(tool);
    setConfigModalVisible(true);
  };

  const handleSaveConfig = async (values: Record<string, unknown>) => {
    if (!currentTool) return;
    await saveToolConfig(currentTool.name, values);
    await loadTools();
  };

  const hasDisabledTools = useMemo(
    () => tools.some((tool) => !tool.enabled),
    [tools],
  );
  const hasEnabledTools = useMemo(
    () => tools.some((tool) => tool.enabled),
    [tools],
  );

  return (
    <div className={styles.toolsPage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("tools.title") }]}
        extra={
          <div className={styles.headerAction}>
            <Switch
              checked={hasEnabledTools && !hasDisabledTools}
              onCheckedChange={() =>
                hasDisabledTools ? enableAll() : disableAll()
              }
              disabled={batchLoading || loading}
            />
          </div>
        }
      />
      <div className={styles.toolsContainer}>
        {loading ? (
          <div className={styles.loading}>
            <p>{t("common.loading")}</p>
          </div>
        ) : tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("tools.emptyState")}
          </p>
        ) : (
          <div className={styles.toolsGrid}>
            {tools.map((tool) => (
              <Card
                key={tool.name}
                className={`${styles.toolCard} ${
                  tool.enabled ? styles.enabledCard : ""
                }`}
              >
                <CardContent className="p-0">
                  <div className={styles.cardHeader}>
                    <h3 className={styles.toolName}>
                      <ToolIcon icon={tool.icon} name={tool.name} /> {tool.name}
                    </h3>
                    <div className={styles.statusContainer}>
                      <span className={styles.statusDot} />
                      <span className={styles.statusText}>
                        {tool.enabled
                          ? t("common.enabled")
                          : t("common.disabled")}
                      </span>
                    </div>
                  </div>

                  <p className={styles.toolDescription}>{tool.description}</p>

                  {tool.requires_config && (
                    <div className={styles.configStatus}>
                      {tool.config_values &&
                      Object.keys(tool.config_values).length > 0 ? (
                        <span className={styles.configured}>
                          {t("tools.configured")}
                        </span>
                      ) : (
                        <span className={styles.notConfigured}>
                          {t("tools.requiresConfig")}
                        </span>
                      )}
                    </div>
                  )}

                  <div className={styles.cardFooter}>
                    {[
                      "execute_shell_command",
                      "delegate_external_agent",
                    ].includes(tool.name) && (
                      <Button
                        variant="outline"
                        size="sm"
                        className={styles.toggleButton}
                        onClick={() => toggleAsyncExecution(tool)}
                        disabled={!tool.enabled}
                      >
                        {tool.async_execution ? (
                          <Zap size={14} className="mr-1" />
                        ) : (
                          <Clock size={14} className="mr-1" />
                        )}
                        {tool.async_execution
                          ? t("tools.asyncExecutionEnabled")
                          : t("tools.asyncExecutionDisabled")}
                      </Button>
                    )}
                    {tool.requires_config && (
                      <Button
                        variant="outline"
                        size="sm"
                        className={styles.toggleButton}
                        onClick={() => handleConfigure(tool)}
                      >
                        <Settings size={14} className="mr-1" />
                        {t("tools.configure")}
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      className={styles.toggleButton}
                      onClick={() => handleToggle(tool)}
                    >
                      {tool.enabled ? (
                        <EyeOff size={14} className="mr-1" />
                      ) : (
                        <Eye size={14} className="mr-1" />
                      )}
                      {tool.enabled ? t("common.disable") : t("common.enable")}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {currentTool && (
        <ToolConfigModal
          key={currentTool.name}
          tool={currentTool}
          visible={configModalVisible}
          onClose={() => setConfigModalVisible(false)}
          onSave={handleSaveConfig}
        />
      )}
    </div>
  );
}
