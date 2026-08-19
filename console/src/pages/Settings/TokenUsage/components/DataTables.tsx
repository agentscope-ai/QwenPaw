import { Card, Table } from "@agentscope-ai/design";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { formatCompact } from "../../../../utils/formatNumber";
import styles from "../index.module.less";

interface TokenRow {
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
  tool_calls: number;
}

interface ByModelData extends TokenRow {
  key: string;
  model: string;
}

interface ByDateData extends TokenRow {
  key: string;
  date: string;
}

interface ByAgentData extends TokenRow {
  key: string;
  agent: string;
}

interface DataTablesProps {
  byModelData: ByModelData[];
  byDateData: ByDateData[];
  byAgentData: ByAgentData[];
}

function tokenStatColumns<T extends TokenRow>(titles: {
  prompt: string;
  completion: string;
  total: string;
  calls: string;
  toolCalls: string;
  toolCallsHint: string;
}) {
  return [
    {
      title: titles.prompt,
      dataIndex: "prompt_tokens",
      key: "prompt_tokens",
      render: (v: number) => formatCompact(v),
      sorter: (a: T, b: T) => a.prompt_tokens - b.prompt_tokens,
    },
    {
      title: titles.completion,
      dataIndex: "completion_tokens",
      key: "completion_tokens",
      render: (v: number) => formatCompact(v),
      sorter: (a: T, b: T) => a.completion_tokens - b.completion_tokens,
    },
    {
      title: titles.total,
      key: "total_tokens",
      render: (_: unknown, record: T) =>
        formatCompact(record.prompt_tokens + record.completion_tokens),
      sorter: (a: T, b: T) =>
        a.prompt_tokens +
        a.completion_tokens -
        (b.prompt_tokens + b.completion_tokens),
    },
    {
      title: titles.calls,
      dataIndex: "call_count",
      key: "call_count",
      render: (v: number) => formatCompact(v),
      sorter: (a: T, b: T) => a.call_count - b.call_count,
    },
    {
      title: (
        <Tooltip title={titles.toolCallsHint}>
          <span>{titles.toolCalls}</span>
        </Tooltip>
      ),
      dataIndex: "tool_calls",
      key: "tool_calls",
      render: (v: number) => formatCompact(v),
      sorter: (a: T, b: T) => a.tool_calls - b.tool_calls,
    },
  ];
}

export function DataTables({
  byModelData,
  byDateData,
  byAgentData,
}: DataTablesProps) {
  const { t } = useTranslation();
  const tokenTitles = {
    prompt: t("tokenUsage.promptTokens"),
    completion: t("tokenUsage.completionTokens"),
    total: t("tokenUsage.totalTokens"),
    calls: t("tokenUsage.totalCalls"),
    toolCalls: t("tokenUsage.toolCalls"),
    toolCallsHint: t("tokenUsage.toolCallsHint"),
  };

  return (
    <>
      {byModelData.length > 0 && (
        <Card
          className={`${styles.tableCard} mobile-scroll-x`}
          title={t("tokenUsage.byModel")}
        >
          <Table
            columns={[
              { title: t("tokenUsage.model"), dataIndex: "model", key: "model" },
              ...tokenStatColumns<ByModelData>(tokenTitles),
            ]}
            dataSource={byModelData}
            pagination={{ pageSize: 10 }}
            size="small"
            scroll={{ x: "max-content" }}
          />
        </Card>
      )}

      {byDateData.length > 0 && (
        <Card
          className={`${styles.tableCard} mobile-scroll-x`}
          title={t("tokenUsage.byDate")}
        >
          <Table
            columns={[
              { title: t("tokenUsage.date"), dataIndex: "date", key: "date" },
              ...tokenStatColumns<ByDateData>(tokenTitles),
            ]}
            dataSource={byDateData}
            pagination={{ pageSize: 10 }}
            size="small"
            scroll={{ x: "max-content" }}
          />
        </Card>
      )}

      {byAgentData.length > 0 && (
        <Card
          className={`${styles.tableCard} mobile-scroll-x`}
          title={t("tokenUsage.byAgent")}
        >
          <Table
            columns={[
              { title: t("tokenUsage.agent"), dataIndex: "agent", key: "agent" },
              ...tokenStatColumns<ByAgentData>(tokenTitles),
            ]}
            dataSource={byAgentData}
            pagination={{ pageSize: 10 }}
            size="small"
            scroll={{ x: "max-content" }}
          />
        </Card>
      )}
    </>
  );
}
