import { useMemo } from "react";
import {
  Table,
  Tag,
  Switch,
  Button,
  Tooltip,
  Collapse,
} from "@agentscope-ai/design";
import { Space } from "antd";
import { Eye, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MergedRule } from "../useToolGuard";
import { useTheme } from "../../../../contexts/ThemeContext";
import styles from "../index.module.less";

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "red",
  HIGH: "orange",
  MEDIUM: "gold",
  LOW: "blue",
  INFO: "default",
};

interface RuleTableProps {
  rules: MergedRule[];
  enabled: boolean;
  onToggleRule: (ruleId: string, currentlyDisabled: boolean) => void;
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
  onPreviewRule,
  onEditRule,
  onDeleteRule,
}: RuleTableProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const darkBtnStyle = isDark ? { color: "rgba(255,255,255,0.75)" } : undefined;

  const groupedRules = useMemo(() => groupRulesByCategory(rules), [rules]);

  const columns = [
    {
      title: t("security.rules.id"),
      dataIndex: "id",
      key: "id",
      width: 220,
      render: (id: string, record: MergedRule) => (
        <span style={{ opacity: record.disabled ? 0.4 : 1 }}>{id}</span>
      ),
    },
    {
      title: t("security.rules.severity"),
      dataIndex: "severity",
      key: "severity",
      width: 100,
      render: (sev: string, record: MergedRule) => (
        <Tag
          color={SEVERITY_COLORS[sev] ?? "default"}
          style={{ opacity: record.disabled ? 0.4 : 1 }}
        >
          {sev}
        </Tag>
      ),
    },
    {
      title: t("security.rules.descriptionCol"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (_text: string, record: MergedRule) => {
        const i18nKey = `security.rules.descriptions.${record.id}`;
        const translated = t(i18nKey, { defaultValue: "" });
        const display = translated || record.description;
        return (
          <Tooltip title={display}>
            <span
              style={{
                opacity: record.disabled ? 0.4 : 1,
                display: "block",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {display}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: t("security.rules.source"),
      dataIndex: "source",
      key: "source",
      width: 100,
      render: (source: string, record: MergedRule) => (
        <Tag
          color={source === "builtin" ? "rgba(142, 140, 153, 1)" : "green"}
          style={{ opacity: record.disabled ? 0.4 : 1 }}
        >
          {source === "builtin"
            ? t("security.rules.builtin")
            : t("security.rules.custom")}
        </Tag>
      ),
    },
    {
      title: t("security.rules.actions"),
      key: "actions",
      width: 160,
      render: (_: unknown, record: MergedRule) => (
        <Space size="small">
          <Tooltip
            title={
              record.disabled
                ? t("security.rules.enable")
                : t("security.rules.disable")
            }
          >
            <Switch
              size="small"
              checked={!record.disabled}
              onChange={() => onToggleRule(record.id, record.disabled)}
              disabled={!enabled}
            />
          </Tooltip>
          {record.source === "builtin" && (
            <Button
              type="text"
              size="small"
              onClick={() => onPreviewRule(record)}
              disabled={!enabled}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                ...darkBtnStyle,
              }}
            >
              <Eye size={16} />
            </Button>
          )}
          {record.source === "custom" && (
            <>
              <Tooltip title={t("security.rules.edit")}>
                <Button
                  type="text"
                  size="small"
                  icon={<Pencil size={14} />}
                  onClick={() => onEditRule(record)}
                  disabled={!enabled}
                  style={darkBtnStyle}
                />
              </Tooltip>
              <Tooltip title={t("security.rules.delete")}>
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<Trash2 size={14} />}
                  onClick={() => onDeleteRule(record.id)}
                  disabled={!enabled}
                />
              </Tooltip>
            </>
          )}
        </Space>
      ),
    },
  ];

  const categoryKeys = Object.keys(groupedRules);

  const collapseItems = categoryKeys.map((category) => {
    const categoryRules = groupedRules[category];
    const enabledCount = categoryRules.filter((r) => !r.disabled).length;
    const totalCount = categoryRules.length;
    const categoryLabel =
      t(`security.rules.categories.${category}`, { defaultValue: "" }) ||
      category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

    return {
      key: category,
      label: (
        <span className={styles.collapseCategoryLabel}>
          {categoryLabel}
          <Tag style={{ marginLeft: 8 }}>
            {enabledCount}/{totalCount}
          </Tag>
        </span>
      ),
      children: (
        <Table
          dataSource={categoryRules}
          columns={columns}
          rowKey="id"
          pagination={false}
          size="small"
          className={styles.ruleTable}
        />
      ),
    };
  });

  return (
    <Collapse
      defaultActiveKey={categoryKeys}
      items={collapseItems}
      className={styles.ruleCollapse}
    />
  );
}
