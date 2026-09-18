import { Button, Drawer, Table, Tag } from "@agentscope-ai/design";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../../api/modules/tools";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import styles from "../index.module.less";

interface ToolDetailDrawerProps {
  tool: ToolInfo | null;
  open: boolean;
  onClose: () => void;
}

interface SchemaParamRow {
  key: string;
  name: string;
  type: string;
  required: boolean;
  defaultValue: string;
  description: string;
}

function schemaTypeLabel(schema: Record<string, unknown> | undefined): string {
  if (!schema) return "-";
  if (typeof schema.type === "string") return schema.type;
  if (Array.isArray(schema.anyOf)) {
    const types = schema.anyOf
      .map((item) =>
        item && typeof item === "object"
          ? String((item as Record<string, unknown>).type || "")
          : "",
      )
      .filter(Boolean);
    return types.length ? types.join(" | ") : "any";
  }
  return "object";
}

function buildParamRows(tool: ToolInfo | null): SchemaParamRow[] {
  const schema = (tool?.input_schema || {}) as Record<string, unknown>;
  const properties =
    (schema.properties as Record<string, Record<string, unknown>>) || {};
  const required = new Set(
    Array.isArray(schema.required)
      ? schema.required.map((item) => String(item))
      : [],
  );
  return Object.entries(properties).map(([name, prop]) => ({
    key: name,
    name,
    type: schemaTypeLabel(prop),
    required: required.has(name),
    defaultValue:
      prop && Object.prototype.hasOwnProperty.call(prop, "default")
        ? JSON.stringify(prop.default)
        : "-",
    description: String(prop?.description || "-"),
  }));
}

export function ToolDetailDrawer({
  tool,
  open,
  onClose,
}: ToolDetailDrawerProps) {
  const { t } = useTranslation();
  const rows = useMemo(() => buildParamRows(tool), [tool]);

  return (
    <Drawer
      width={560}
      placement="right"
      title={
        tool
          ? t("tools.detailTitle", { name: tool.name })
          : t("tools.detailTitleFallback")
      }
      open={open}
      onClose={onClose}
      destroyOnHidden
      footer={
        <div className={styles.detailDrawerFooter}>
          <Button onClick={onClose}>{t("common.close")}</Button>
        </div>
      }
    >
      {tool && (
        <div className={styles.detailDrawerBody}>
          <div className={styles.detailMetaRow}>
            <Tag color={tool.enabled ? "success" : "default"}>
              {tool.enabled ? t("common.enabled") : t("common.disabled")}
            </Tag>
          </div>

          <div className={styles.detailSection}>
            <div className={styles.detailSectionTitle}>
              {t("tools.detailAbout")}
            </div>
            <MarkdownCopy
              content={tool.detail || tool.summary || tool.description || "-"}
              editable={false}
              showControls={false}
              showMarkdown
            />
          </div>

          <div className={styles.detailSection}>
            <div className={styles.detailSectionTitle}>
              {t("tools.parameters")}
            </div>
            {rows.length > 0 ? (
              <Table
                size="small"
                pagination={false}
                rowKey="key"
                dataSource={rows}
                columns={[
                  {
                    title: t("tools.paramName"),
                    dataIndex: "name",
                    key: "name",
                    width: 120,
                  },
                  {
                    title: t("tools.paramType"),
                    dataIndex: "type",
                    key: "type",
                    width: 100,
                  },
                  {
                    title: t("tools.paramRequired"),
                    dataIndex: "required",
                    key: "required",
                    width: 80,
                    render: (value: boolean) =>
                      value ? t("common.yes") : t("common.no"),
                  },
                  {
                    title: t("tools.paramDefault"),
                    dataIndex: "defaultValue",
                    key: "defaultValue",
                    width: 90,
                  },
                  {
                    title: t("tools.paramDescription"),
                    dataIndex: "description",
                    key: "description",
                  },
                ]}
              />
            ) : (
              <div className={styles.noParameters}>
                {t("tools.noParameters")}
              </div>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}
