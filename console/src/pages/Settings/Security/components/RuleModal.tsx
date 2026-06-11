import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranslation } from "react-i18next";
import type { ToolGuardRule } from "../../../../api/modules/security";

const SEVERITY_OPTIONS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const CATEGORY_OPTIONS = [
  "command_injection",
  "code_execution",
  "data_exfiltration",
  "path_traversal",
  "sensitive_file_access",
  "network_abuse",
  "credential_exposure",
  "resource_abuse",
  "privilege_escalation",
  "prompt_injection",
];
const BUILTIN_TOOLS = [
  "execute_shell_command",
  "execute_python_code",
  "browser_use",
  "desktop_screenshot",
  "view_image",
  "read_file",
  "write_file",
  "edit_file",
  "append_file",
  "view_text_file",
  "write_text_file",
  "send_file_to_user",
];

interface RuleFormValues {
  id: string;
  tools: string[];
  params: string[];
  severity: string;
  category: string;
  patterns: string;
  exclude_patterns: string;
  description: string;
  remediation: string;
}

interface RuleModalProps {
  open: boolean;
  editingRule: ToolGuardRule | null;
  existingRuleIds: string[];
  onOk: (values: RuleFormValues) => void;
  onCancel: () => void;
}

function TagInput({
  label,
  values,
  onChange,
  suggestions,
  placeholder,
}: {
  label?: string;
  values: string[];
  onChange: (vals: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
}) {
  const [input, setInput] = useState("");

  const addTag = (val: string) => {
    const trimmed = val.trim();
    if (trimmed && !values.includes(trimmed)) {
      onChange([...values, trimmed]);
    }
    setInput("");
  };

  const removeTag = (tag: string) => {
    onChange(values.filter((v) => v !== tag));
  };

  return (
    <div className="flex flex-col gap-1">
      {label && <span className="text-xs text-muted-foreground">{label}</span>}
      <div className="flex flex-wrap gap-1 min-h-[32px] border rounded-md px-2 py-1 focus-within:ring-1 focus-within:ring-ring">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 bg-secondary text-secondary-foreground text-xs rounded px-2 py-0.5"
          >
            {v}
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground leading-none"
              onClick={() => removeTag(v)}
            >
              ×
            </button>
          </span>
        ))}
        <input
          className="flex-1 min-w-[80px] outline-none text-sm bg-transparent"
          placeholder={placeholder}
          value={input}
          list={suggestions ? "tag-suggestions" : undefined}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addTag(input);
            } else if (e.key === "Backspace" && !input && values.length > 0) {
              removeTag(values[values.length - 1]);
            }
          }}
        />
        {suggestions && (
          <datalist id="tag-suggestions">
            {suggestions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        )}
      </div>
    </div>
  );
}

export function RuleModal({
  open,
  editingRule,
  existingRuleIds,
  onOk,
  onCancel,
}: RuleModalProps) {
  const { t } = useTranslation();

  const [id, setId] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [params, setParams] = useState<string[]>([]);
  const [severity, setSeverity] = useState("HIGH");
  const [category, setCategory] = useState("command_injection");
  const [patterns, setPatterns] = useState("");
  const [excludePatterns, setExcludePatterns] = useState("");
  const [description, setDescription] = useState("");
  const [remediation, setRemediation] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      if (editingRule) {
        setId(editingRule.id);
        setTools(editingRule.tools ?? []);
        setParams(editingRule.params ?? []);
        setSeverity(editingRule.severity ?? "HIGH");
        setCategory(editingRule.category ?? "command_injection");
        setPatterns(editingRule.patterns.join("\n"));
        setExcludePatterns(editingRule.exclude_patterns.join("\n"));
        setDescription(editingRule.description ?? "");
        setRemediation(editingRule.remediation ?? "");
      } else {
        setId("");
        setTools([]);
        setParams([]);
        setSeverity("HIGH");
        setCategory("command_injection");
        setPatterns("");
        setExcludePatterns("");
        setDescription("");
        setRemediation("");
      }
      setErrors({});
    }
  }, [open, editingRule]);

  const handleOk = () => {
    const newErrors: Record<string, string> = {};
    if (!id.trim()) {
      newErrors.id = t("security.rules.ruleIdRequired");
    } else if (!editingRule && existingRuleIds.includes(id.trim())) {
      newErrors.id = t("security.rules.duplicateId");
    }
    if (!patterns.trim()) {
      newErrors.patterns = t("security.rules.patternsRequired");
    }
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    onOk({
      id: id.trim(),
      tools,
      params,
      severity,
      category,
      patterns,
      exclude_patterns: excludePatterns,
      description,
      remediation,
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onCancel();
      }}
    >
      <DialogContent className="max-w-[640px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {editingRule
              ? t("security.rules.editTitle")
              : t("security.rules.addTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="rule-id">{t("security.rules.ruleId")}</Label>
            <Input
              id="rule-id"
              placeholder="TOOL_CMD_CUSTOM_RULE"
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                if (errors.id) setErrors((p) => ({ ...p, id: "" }));
              }}
              disabled={!!editingRule}
            />
            {errors.id && (
              <span className="text-xs text-destructive">{errors.id}</span>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("security.rules.tools")}</Label>
            <TagInput
              values={tools}
              onChange={setTools}
              suggestions={BUILTIN_TOOLS}
              placeholder={t("security.rules.toolsPlaceholder")}
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("security.rules.params")}</Label>
            <TagInput
              values={params}
              onChange={setParams}
              placeholder={t("security.rules.paramsPlaceholder")}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1">
              <Label>{t("security.rules.severityLabel")}</Label>
              <Select value={severity} onValueChange={setSeverity}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SEVERITY_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1">
              <Label>{t("security.rules.categoryLabel")}</Label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {t(`security.rules.categories.${c}`, { defaultValue: c })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("security.rules.patterns")}</Label>
            <Textarea
              rows={3}
              placeholder={"\\brm\\b\n\\bmv\\b"}
              className="font-mono"
              value={patterns}
              onChange={(e) => {
                setPatterns(e.target.value);
                if (errors.patterns) setErrors((p) => ({ ...p, patterns: "" }));
              }}
            />
            {errors.patterns && (
              <span className="text-xs text-destructive">
                {errors.patterns}
              </span>
            )}
            <span className="text-xs text-muted-foreground">
              {t("security.rules.patternsTooltip")}
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("security.rules.excludePatterns")}</Label>
            <Textarea
              rows={2}
              placeholder={"^#"}
              className="font-mono"
              value={excludePatterns}
              onChange={(e) => setExcludePatterns(e.target.value)}
            />
            <span className="text-xs text-muted-foreground">
              {t("security.rules.excludePatternsTooltip")}
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("security.rules.descriptionLabel")}</Label>
            <Input
              placeholder={t("security.rules.descriptionPlaceholder")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("security.rules.remediationLabel")}</Label>
            <Input
              placeholder={t("security.rules.remediationPlaceholder")}
              value={remediation}
              onChange={(e) => setRemediation(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleOk}>{t("common.confirm")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
