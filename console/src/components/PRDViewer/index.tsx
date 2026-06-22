import { useState, useEffect, useMemo, useRef } from "react";
import {
  Table,
  Tag,
  Typography,
  Space,
  Tooltip,
  Spin,
  Descriptions,
  theme,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  CheckCircleOutlined,
  FieldTimeOutlined,
  FileTextOutlined,
  CaretRightOutlined,
  CaretUpOutlined,
} from "@ant-design/icons";
import styles from "./index.module.less";

const { Text } = Typography;

/** Parse the tool call arguments from the message content. */
function parseToolArgs(data: unknown): Record<string, unknown> {
  const firstData = (data as any)?.content?.[0]?.data;
  const rawArgs = firstData?.arguments;
  if (typeof rawArgs === "string") {
    try {
      return JSON.parse(rawArgs);
    } catch {
      return {};
    }
  }
  return rawArgs ?? {};
}

/** Extract the tool result text from the output field. */
function extractOutputText(output: unknown): string | null {
  if (!output) return null;
  if (typeof output === "string") {
    try {
      const parsed = JSON.parse(output);
      if (Array.isArray(parsed)) {
        const textBlock = parsed.find(
          (b: unknown) => (b as any)?.type === "text" && (b as any)?.text,
        );
        return (textBlock as any)?.text ?? null;
      }
      if (typeof parsed === "string") return parsed;
    } catch {
      return output;
    }
  }
  if (Array.isArray(output)) {
    const textBlock = output.find(
      (b: unknown) => (b as any)?.type === "text" && (b as any)?.text,
    );
    return (textBlock as any)?.text ?? null;
  }
  return null;
}

interface AcceptanceCellProps {
  criteria: unknown;
}

function AcceptanceCell({ criteria }: AcceptanceCellProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  if (typeof criteria === "string") {
    return (
      <div className={styles.acceptanceText}>
        {criteria.length > 100 ? criteria.slice(0, 100) + "..." : criteria}
      </div>
    );
  }
  if (Array.isArray(criteria)) {
    const items = expanded ? criteria : criteria.slice(0, 3);
    const restCount = criteria.length - 3;
    return (
      <div className={styles.acceptanceText}>
        {items.map((item: string, i: number) => (
          <div key={i} style={{ marginBottom: 4 }}>
            · {item}
          </div>
        ))}
        {restCount > 0 && !expanded && (
          <div
            className={styles.expandTrigger}
            onClick={() => setExpanded(true)}
          >
            <CaretRightOutlined style={{ fontSize: 10 }} />
            {t("managePrd.expandMore", { count: restCount })}
          </div>
        )}
        {expanded && restCount > 0 && (
          <div
            className={styles.expandTrigger}
            onClick={() => setExpanded(false)}
          >
            <CaretUpOutlined style={{ fontSize: 10 }} />
            {t("managePrd.collapse")}
          </div>
        )}
      </div>
    );
  }
  return <div className={styles.acceptanceText}>-</div>;
}

interface PRDViewerProps {
  data: unknown;
}

export function PRDViewer({ data }: PRDViewerProps) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const [prd, setPrd] = useState<Record<string, unknown> | null>(null);
  const [fetchError, setFetchError] = useState(false);

  const isLoading =
    (data as any)?.status === "in_progress" ||
    (data as any)?.status === "created";

  const loopDir = useMemo(() => {
    const args = parseToolArgs(data);
    return (args?.loop_dir as string) || null;
  }, [data]);

  const toolResult = useMemo(() => {
    const outputText = extractOutputText(
      (data as any)?.content?.[1]?.data?.output,
    );
    if (!outputText) return null;
    try {
      return JSON.parse(outputText);
    } catch {
      return null;
    }
  }, [data]);

  const isSuccess = (toolResult as any)?.status === "ok";
  const isError = (toolResult as any)?.status === "error";
  const errorMessage = isError
    ? ((toolResult as any)?.message as string) || t("managePrd.unknownError")
    : null;

  // Fetch PRD when tool result is ready. Track the last fetched
  // request key (loopDir + timestamp) to avoid infinite loop caused
  // by toolResult being a new object each render, while still allowing
  // different missions / operations to fetch correctly.
  const lastFetchKey = useRef<string | null>(null);

  useEffect(() => {
    if (!isLoading && isSuccess && loopDir) {
      const ts = (toolResult as any)?.data?.timestamp;
      const key = `${loopDir}|${ts || ""}`;
      if (key === lastFetchKey.current) return;

      (async () => {
        if (!loopDir) return;
        try {
          const host = (window as any).QwenPaw?.host;
          if (!host) return;
          const token = host.getApiToken();
          const headers: Record<string, string> = {};
          if (token) headers["Authorization"] = `Bearer ${token}`;
          let url = `/prd?loop_dir=${encodeURIComponent(loopDir)}`;
          if (ts) {
            url += `&timestamp=${encodeURIComponent(ts)}`;
          }
          const res = await fetch(host.getApiUrl(url), { headers });
          if (!res.ok) {
            setFetchError(true);
            return;
          }
          const json = await res.json();
          if (json && Array.isArray(json.userStories)) {
            setPrd(json);
            setFetchError(false);
            lastFetchKey.current = key;
          } else {
            setFetchError(true);
          }
        } catch {
          setFetchError(true);
        }
      })();
    }
  }, [isLoading, isSuccess, loopDir, toolResult]);

  if (isLoading) {
    return (
      <div
        className={styles.loadingContainer}
        style={{
          background: token.colorBgContainer,
          borderColor: token.colorBorderSecondary,
        }}
      >
        <Spin size="default" />
        <Text type="secondary" style={{ fontSize: 13 }}>
          {t("managePrd.loading")}
        </Text>
      </div>
    );
  }

  if (isError) {
    return (
      <div
        className={styles.errorContainer}
        style={{
          background: token.colorErrorBg,
          borderColor: token.colorErrorBorder,
        }}
      >
        <Text type="danger" style={{ fontSize: 13 }}>
          {t("managePrd.errorPrefix")}
          {errorMessage}
        </Text>
      </div>
    );
  }

  if (!isSuccess || fetchError || !prd) return null;

  const stories = prd.userStories as Array<Record<string, unknown>>;
  const sortedStories = [...stories].sort((a, b) =>
    (a.id as string).localeCompare(b.id as string, undefined, {
      numeric: true,
    }),
  );
  const passedCount = stories.filter((s) => s.passes).length;

  const storyColumns = [
    {
      title: t("managePrd.status"),
      key: "status",
      align: "center" as const,
      render: (_: unknown, record: Record<string, unknown>) => {
        if (record.passes) {
          return (
            <Tooltip title={t("managePrd.completed")}>
              <CheckCircleOutlined style={{ color: "#52c41a", fontSize: 18 }} />
            </Tooltip>
          );
        }
        return (
          <Tooltip title={t("managePrd.pending")}>
            <FieldTimeOutlined style={{ color: "#faad14", fontSize: 18 }} />
          </Tooltip>
        );
      },
    },
    {
      title: t("managePrd.id"),
      dataIndex: "id",
      key: "id",
      align: "center" as const,
      render: (val: string) => <Tag className={styles.idTag}>{val}</Tag>,
    },
    {
      title: t("managePrd.title"),
      dataIndex: "title",
      key: "title",
      align: "center" as const,
      ellipsis: true,
      render: (val: string) => (
        <Text strong style={{ fontSize: 12 }}>
          {val}
        </Text>
      ),
    },
    {
      title: t("managePrd.priority"),
      key: "priority",
      align: "center" as const,
      render: (_: unknown, record: Record<string, unknown>) => {
        const p = record.priority;
        return (
          <Tag color="default" style={{ fontSize: 12 }}>
            {p != null ? String(p) : "-"}
          </Tag>
        );
      },
    },
    {
      title: t("managePrd.description"),
      dataIndex: "description",
      key: "description",
      onHeaderCell: () => ({
        style: { textAlign: "center" as const },
      }),
      onCell: () => ({
        style: {
          maxWidth: 280,
          whiteSpace: "normal" as const,
          wordBreak: "break-word" as const,
        },
      }),
      ellipsis: true,
      render: (val: string) => (
        <div className={styles.acceptanceText}>{val || "-"}</div>
      ),
    },
    {
      title: t("managePrd.acceptance"),
      key: "acceptance",
      onHeaderCell: () => ({
        style: { textAlign: "center" as const },
      }),
      fixed: "right" as const,
      onCell: () => ({
        style: {
          maxWidth: 280,
          whiteSpace: "normal" as const,
          wordBreak: "break-word" as const,
        },
      }),
      render: (_: unknown, record: Record<string, unknown>) => (
        <AcceptanceCell criteria={record.acceptanceCriteria} />
      ),
    },
  ];

  return (
    <div
      className={styles.container}
      style={{
        background: token.colorBgContainer,
        borderColor: token.colorBorderSecondary,
      }}
    >
      {/* Header */}
      <div className={styles.header}>
        <Space size={8}>
          <FileTextOutlined className={styles.headerIcon} />
          <Text strong>{(prd.project as string) || "PRD"}</Text>
        </Space>
      </div>

      {/* Progress info */}
      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, md: 3 }}
        style={{ marginBottom: 12 }}
        bordered={false}
        items={[
          {
            key: "progress",
            label: t("managePrd.progress"),
            children: `${passedCount}/${stories.length} ${t(
              "managePrd.completed",
            )}`,
          },
        ]}
      />

      {/* Story table */}
      <Table
        columns={storyColumns}
        dataSource={sortedStories.map((s) => ({ ...s, key: s.id }))}
        size="small"
        pagination={false}
        tableLayout="auto"
        scroll={{ x: "max-content" as const }}
        style={{ marginBottom: 4 }}
      />

      {/* Legend */}
      <div className={styles.legend}>
        <CheckCircleOutlined style={{ color: "#52c41a", fontSize: 14 }} />
        <span>{t("managePrd.completed")}</span>
        <span style={{ margin: "0 4px" }}>·</span>
        <FieldTimeOutlined style={{ color: "#faad14", fontSize: 14 }} />
        <span>{t("managePrd.pending")}</span>
      </div>
    </div>
  );
}
