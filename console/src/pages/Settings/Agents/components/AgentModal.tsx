import { useEffect, useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, Check, PackageOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AgentSummary } from "@/api/types/agents";
import type { ProviderInfo } from "@/api/types/provider";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { PoolSkillSpec } from "@/api/types/skill";
import { skillApi } from "@/api/modules/skill";
import { providerApi } from "@/api/modules/provider";
import { providerIcon } from "../../Models/components/providerIcon";
import styles from "../index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  models: Array<{ id: string; name: string }>;
}

export interface AgentFormValues {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
  active_model_provider: string | undefined;
  active_model_model: string | undefined;
}

export interface AgentFormRef {
  getValues: () => AgentFormValues;
  setValues: (vals: Partial<AgentFormValues>) => void;
  resetFields: () => void;
  validateFields: () => Promise<AgentFormValues>;
}

interface AgentModalProps {
  open: boolean;
  editingAgent: AgentSummary | null;
  formRef: AgentFormRef;
  selectedSkills: string[];
  onSelectedSkillsChange: (skills: string[]) => void;
  onInstalledSkillsLoaded: (skills: string[]) => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
}

const EMPTY_FORM: AgentFormValues = {
  id: "",
  name: "",
  description: "",
  workspace_dir: "",
  active_model_provider: undefined,
  active_model_model: undefined,
};

export function useAgentForm(): AgentFormRef {
  const [values, setValues] = useState<AgentFormValues>(EMPTY_FORM);
  return {
    getValues: () => values,
    setValues: (partial) => {
      setValues((prev) => ({ ...prev, ...partial }));
    },
    resetFields: () => {
      setValues(EMPTY_FORM);
    },
    validateFields: () => {
      if (!values.name.trim()) return Promise.reject({ name: "required" });
      return Promise.resolve(values);
    },
  };
}

export function AgentModal({
  open,
  editingAgent,
  formRef,
  selectedSkills,
  onSelectedSkillsChange,
  onInstalledSkillsLoaded,
  onSave,
  onCancel,
}: AgentModalProps) {
  const { t } = useTranslation();
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [installedSkills, setInstalledSkills] = useState<string[]>([]);
  const [loadingSkills, setLoadingSkills] = useState(false);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [saving, setSaving] = useState(false);
  const [nameError, setNameError] = useState("");

  // Internal controlled form state — synced to formRef
  const [formVals, setFormVals] = useState<AgentFormValues>(EMPTY_FORM);

  const setField = <K extends keyof AgentFormValues>(
    key: K,
    value: AgentFormValues[K],
  ) => {
    const updated = { ...formVals, [key]: value };
    setFormVals(updated);
    formRef.setValues({ [key]: value });
  };

  // Sync when formRef.setValues is called externally (via parent)
  useEffect(() => {
    if (open) {
      const vals = formRef.getValues();
      setFormVals(vals);
      setNameError("");
    }
  }, [open]);

  const eligibleProviders: EligibleProvider[] = useMemo(() => {
    return providers
      .filter((p) => {
        const hasModels =
          (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
        if (!hasModels) return false;
        if (p.require_api_key === false) return !!p.base_url;
        if (p.is_custom) return !!p.base_url;
        if (p.require_api_key ?? true) return !!p.api_key;
        return true;
      })
      .map((p) => ({
        id: p.id,
        name: p.name,
        models: [...(p.models ?? []), ...(p.extra_models ?? [])],
      }));
  }, [providers]);

  const availableModels = useMemo(() => {
    if (!formVals.active_model_provider) return [];
    return (
      eligibleProviders.find((p) => p.id === formVals.active_model_provider)
        ?.models ?? []
    );
  }, [formVals.active_model_provider, eligibleProviders]);

  useEffect(() => {
    if (!open) return;

    setLoadingProviders(true);
    providerApi
      .listProviders()
      .then((data) => {
        if (Array.isArray(data)) setProviders(data);
      })
      .catch((err) => console.error("Failed to load providers:", err))
      .finally(() => setLoadingProviders(false));

    setLoadingSkills(true);
    const fetchPool = skillApi.listSkillPoolSkills();
    const fetchInstalled = editingAgent
      ? skillApi.listSkills(editingAgent.id)
      : Promise.resolve([]);

    Promise.all([fetchPool, fetchInstalled])
      .then(([pool, workspaceSkills]) => {
        const poolSkillNames = new Set(pool.map((s) => s.name));
        const installed = workspaceSkills
          .filter((s) => poolSkillNames.has(s.name))
          .map((s) => s.name);
        setPoolSkills(pool);
        setInstalledSkills(installed);
        onInstalledSkillsLoaded(installed);
        onSelectedSkillsChange(editingAgent ? installed : []);
      })
      .finally(() => setLoadingSkills(false));
  }, [editingAgent, onInstalledSkillsLoaded, onSelectedSkillsChange, open]);

  const handleProviderChange = (providerId: string) => {
    const updated = {
      ...formVals,
      active_model_provider: providerId,
      active_model_model: undefined,
    };
    setFormVals(updated);
    formRef.setValues(updated);
  };

  const handleModelChange = (modelId: string) => {
    setField("active_model_model", modelId);
  };

  const handleClearModel = () => {
    const updated = {
      ...formVals,
      active_model_provider: undefined,
      active_model_model: undefined,
    };
    setFormVals(updated);
    formRef.setValues(updated);
  };

  const toggleSkill = (name: string) => {
    if (editingAgent && installedSkills.includes(name)) return;
    onSelectedSkillsChange(
      selectedSkills.includes(name)
        ? selectedSkills.filter((s) => s !== name)
        : [...selectedSkills, name],
    );
  };

  const handleSelectAll = () =>
    onSelectedSkillsChange(poolSkills.map((s) => s.name));
  const handleSelectBuiltin = () => {
    const builtinNames = poolSkills
      .filter((s) => s.source === "builtin")
      .map((s) => s.name);
    onSelectedSkillsChange(
      Array.from(new Set([...installedSkills, ...builtinNames])),
    );
  };
  const handleSelectNone = () =>
    onSelectedSkillsChange(editingAgent ? [...installedSkills] : []);

  const handleSave = async () => {
    if (!formVals.name.trim()) {
      setNameError(t("agent.nameRequired"));
      return;
    }
    setNameError("");
    setSaving(true);
    try {
      await onSave();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onCancel();
      }}
    >
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {editingAgent
              ? t("agent.editTitle", {
                  name: getAgentDisplayName(editingAgent, t),
                })
              : t("agent.createTitle")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {editingAgent
              ? t("agent.editTitle", {
                  name: getAgentDisplayName(editingAgent, t),
                })
              : t("agent.createTitle")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* ID */}
          <div className="space-y-1.5">
            <Label htmlFor="agent-id">
              {editingAgent ? t("agent.id") : t("agent.idLabel")}
            </Label>
            {editingAgent ? (
              <Input id="agent-id" value={formVals.id} disabled />
            ) : (
              <>
                <Input
                  id="agent-id"
                  value={formVals.id}
                  placeholder={t("agent.idPlaceholder")}
                  onChange={(e) => setField("id", e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  {t("agent.idHelp")}
                </p>
              </>
            )}
          </div>

          {/* Name */}
          <div className="space-y-1.5">
            <Label htmlFor="agent-name">
              {t("agent.name")} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="agent-name"
              value={formVals.name}
              placeholder={t("agent.namePlaceholder")}
              onChange={(e) => {
                setField("name", e.target.value);
                if (nameError) setNameError("");
              }}
            />
            {nameError && (
              <p className="text-xs text-destructive">{nameError}</p>
            )}
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="agent-desc">{t("agent.description")}</Label>
            <Textarea
              id="agent-desc"
              value={formVals.description}
              placeholder={t("agent.descriptionPlaceholder")}
              rows={3}
              onChange={(e) => setField("description", e.target.value)}
            />
          </div>

          {/* Model */}
          <div className="space-y-1.5">
            <Label>{t("agent.model")}</Label>
            <div className="flex gap-2">
              <div className="flex-1">
                <Select
                  value={formVals.active_model_provider ?? ""}
                  onValueChange={handleProviderChange}
                  disabled={loadingProviders}
                >
                  <SelectTrigger className="w-full">
                    {loadingProviders ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <SelectValue placeholder={t("agent.modelPlaceholder")} />
                    )}
                  </SelectTrigger>
                  <SelectContent>
                    {eligibleProviders.length === 0 ? (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">
                        {t("agent.noConfiguredModels")}
                      </div>
                    ) : (
                      eligibleProviders.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          <div className="flex items-center gap-1.5">
                            <img
                              src={providerIcon(p.id)}
                              alt=""
                              className="w-4 h-4"
                            />
                            <span>{p.name}</span>
                          </div>
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1">
                <Select
                  value={formVals.active_model_model ?? ""}
                  onValueChange={handleModelChange}
                  disabled={!formVals.active_model_provider}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue
                      placeholder={
                        formVals.active_model_provider
                          ? t("models.model")
                          : t("agent.modelPlaceholder")
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {availableModels.map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.name || m.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {(formVals.active_model_provider ||
                formVals.active_model_model) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleClearModel}
                  type="button"
                >
                  {t("common.clear", "Clear")}
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {t("agent.modelHelp")}
            </p>
          </div>

          {/* Workspace */}
          <div className="space-y-1.5">
            <Label htmlFor="agent-workspace">{t("agent.workspace")}</Label>
            <Input
              id="agent-workspace"
              value={formVals.workspace_dir}
              placeholder="~/.qwenpaw/workspaces/my-agent"
              disabled={!!editingAgent}
              onChange={(e) => setField("workspace_dir", e.target.value)}
            />
            {!editingAgent && (
              <p className="text-xs text-muted-foreground">
                {t("agent.workspaceHelp")}
              </p>
            )}
          </div>

          {/* Skills */}
          <div className="space-y-2 pt-2 border-t">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                {editingAgent
                  ? t("agent.addSkillsToAgent")
                  : t("agent.initialSkills")}
              </p>
              <div className="flex gap-1">
                <Button
                  size="sm"
                  variant="default"
                  onClick={handleSelectAll}
                  type="button"
                >
                  {t("agent.selectAll")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSelectBuiltin}
                  type="button"
                >
                  {t("agent.selectBuiltin")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSelectNone}
                  type="button"
                >
                  {t("agent.selectNone")}
                </Button>
              </div>
            </div>

            {loadingSkills ? (
              <div className="flex justify-center py-4">
                <Loader2 className="animate-spin" size={20} />
              </div>
            ) : poolSkills.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-4 text-muted-foreground">
                <PackageOpen size={32} strokeWidth={1} />
                <span className="text-sm">{t("agent.noPoolSkills")}</span>
              </div>
            ) : (
              <div className={styles.pickerGrid}>
                {poolSkills.map((skill) => {
                  const selected = selectedSkills.includes(skill.name);
                  const isInstalled =
                    !!editingAgent && installedSkills.includes(skill.name);
                  return (
                    <div
                      key={skill.name}
                      className={`${styles.pickerCard} ${
                        selected ? styles.pickerCardSelected : ""
                      } ${isInstalled ? styles.pickerCardDisabled : ""}`}
                      onClick={() => toggleSkill(skill.name)}
                    >
                      {selected && (
                        <span className={styles.pickerCheck}>
                          <Check size={12} />
                        </span>
                      )}
                      <div className={styles.pickerCardTitle}>{skill.name}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin mr-1" />}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
