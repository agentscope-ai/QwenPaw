import { Table, Tag, Switch, Button, Tooltip } from "@agentscope-ai/design";
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
          color={source === "builtin" ? "geekblue" : "green"}
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
                gap: 4,
                ...darkBtnStyle,
              }}
            >
              <Eye size={14} />
              {t("security.rules.preview")}
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

  return (
    <Table
      dataSource={rules}
      columns={columns}
      rowKey="id"
      pagination={false}
      size="small"
      className={styles.ruleTable}
    />
  );
}
