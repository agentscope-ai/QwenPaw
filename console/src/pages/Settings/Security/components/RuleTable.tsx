import { useMemo, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Eye, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MergedRule } from "../useToolGuard";
import styles from "../index.module.less";

const SEVERITY_CLASS: Record<string, string> = {
  CRITICAL: "border-red-400 text-red-600",
  HIGH: "border-orange-400 text-orange-600",
  MEDIUM: "border-yellow-400 text-yellow-600",
  LOW: "border-blue-400 text-blue-600",
  INFO: "",
};

interface RuleTableProps {
  rules: MergedRule[];
  enabled: boolean;
  onToggleRule: (ruleId: string, currentlyDisabled: boolean) => void;
  onToggleAutoDeny: (ruleId: string, currentlyAutoDeny: boolean) => void;
  onPreviewRule: (rule: MergedRule) => void;
  onEditRule: (rule: MergedRule) => void;
  onDeleteRule: (ruleId: string) => void;
}

function groupRulesByCategory(
  rules: MergedRule[],
): Record<string, MergedRule[]> {
  const groups: Record<string, MergedRule[]> = {};
  for (const rule of rules) {
    const category = rule.category || "other";
    if (!groups[category]) {
      groups[category] = [];
    }
    groups[category].push(rule);
  }
  return groups;
}

export function RuleTable({
  rules,
  enabled,
  onToggleRule,
  onToggleAutoDeny,
  onPreviewRule,
  onEditRule,
  onDeleteRule,
}: RuleTableProps) {
  const { t } = useTranslation();

  const groupedRules = useMemo(() => groupRulesByCategory(rules), [rules]);
  const categoryKeys = Object.keys(groupedRules);

  const [openItems, setOpenItems] = useState<string[]>(categoryKeys);

  return (
    <Accordion
      type="multiple"
      value={openItems}
      onValueChange={setOpenItems}
      className={styles.ruleCollapse}
    >
      {categoryKeys.map((category) => {
        const categoryRules = groupedRules[category];
        const enabledCount = categoryRules.filter((r) => !r.disabled).length;
        const totalCount = categoryRules.length;
        const categoryLabel =
          t(`security.rules.categories.${category}`, { defaultValue: "" }) ||
          category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

        return (
          <AccordionItem key={category} value={category}>
            <AccordionTrigger className={styles.collapseCategoryLabel}>
              <span>
                {categoryLabel}
                <Badge variant="outline" className="ml-2 text-xs">
                  {enabledCount}/{totalCount}
                </Badge>
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <Table className={styles.ruleTable}>
                <TableHeader>
                  <TableRow>
                    <TableHead style={{ width: 280 }}>
                      {t("security.rules.id")}
                    </TableHead>
                    <TableHead style={{ width: 100 }}>
                      {t("security.rules.severity")}
                    </TableHead>
                    <TableHead>{t("security.rules.descriptionCol")}</TableHead>
                    <TableHead style={{ width: 100 }}>
                      {t("security.rules.source")}
                    </TableHead>
                    <TableHead style={{ width: 100 }}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-default">
                            {t("security.rules.autoDeny")}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>
                          {t("security.rules.autoDenyTooltip")}
                        </TooltipContent>
                      </Tooltip>
                    </TableHead>
                    <TableHead style={{ width: 120 }}>
                      {t("security.rules.actions")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {categoryRules.map((record) => {
                    const i18nKey = `security.rules.descriptions.${record.id}`;
                    const translated = t(i18nKey, { defaultValue: "" });
                    const display = translated || record.description;

                    return (
                      <TableRow key={record.id}>
                        <TableCell>
                          <span style={{ opacity: record.disabled ? 0.4 : 1 }}>
                            {record.id}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-xs ${
                              SEVERITY_CLASS[record.severity] ?? ""
                            }`}
                            style={{ opacity: record.disabled ? 0.4 : 1 }}
                          >
                            {record.severity}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                className="block overflow-hidden text-ellipsis whitespace-nowrap max-w-[240px]"
                                style={{ opacity: record.disabled ? 0.4 : 1 }}
                              >
                                {display}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>{display}</TooltipContent>
                          </Tooltip>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-xs ${
                              record.source === "builtin"
                                ? "border-gray-400 text-gray-600"
                                : "border-green-400 text-green-600"
                            }`}
                            style={{ opacity: record.disabled ? 0.4 : 1 }}
                          >
                            {record.source === "builtin"
                              ? t("security.rules.builtin")
                              : t("security.rules.custom")}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span>
                                <Switch
                                  checked={record.autoDeny}
                                  onCheckedChange={() =>
                                    onToggleAutoDeny(record.id, record.autoDeny)
                                  }
                                  disabled={!enabled || record.disabled}
                                />
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              {record.autoDeny
                                ? t("security.rules.autoDenyDisable")
                                : t("security.rules.autoDenyEnable")}
                            </TooltipContent>
                          </Tooltip>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span>
                                  <Switch
                                    checked={!record.disabled}
                                    onCheckedChange={() =>
                                      onToggleRule(record.id, record.disabled)
                                    }
                                    disabled={!enabled}
                                  />
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                {record.disabled
                                  ? t("security.rules.enable")
                                  : t("security.rules.disable")}
                              </TooltipContent>
                            </Tooltip>
                            {record.source === "builtin" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => onPreviewRule(record)}
                                disabled={!enabled}
                              >
                                <Eye size={16} />
                              </Button>
                            )}
                            {record.source === "custom" && (
                              <>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-7 w-7 p-0"
                                      onClick={() => onEditRule(record)}
                                      disabled={!enabled}
                                    >
                                      <Pencil size={14} />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    {t("security.rules.edit")}
                                  </TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                                      onClick={() => onDeleteRule(record.id)}
                                      disabled={!enabled}
                                    >
                                      <Trash2 size={14} />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    {t("security.rules.delete")}
                                  </TooltipContent>
                                </Tooltip>
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}
