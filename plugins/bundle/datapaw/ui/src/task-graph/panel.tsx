import type { PlanSnapshot } from "./types";
import { getStatusConfig, isClickable } from "./constants";
import { tTaskGraph } from "./i18n";
import { createHighlightIcon } from "../lib/icons";
import type { HostBundle } from "../types";

const STATUS_COL_WIDTH = 108;

type HostReact = typeof import("react");
type HostAntd = HostBundle["antd"];

type PlanCorrectionPopoverComponent = React.ComponentType<{
  plan: PlanSnapshot;
  children: React.ReactNode;
  onConfirm?: (yaml: string) => void;
}>;

export interface TaskGraphPanelProps {
  plan: PlanSnapshot;
  React: HostReact;
  antd: HostAntd;
  PlanCorrectionPopover?: PlanCorrectionPopoverComponent;
  showActions?: boolean;
  onNodeClick?: (nodeId: string) => void;
  onPlanCorrection?: (yaml: string) => void;
}

export function TaskGraphPanel({
  plan,
  React,
  antd,
  PlanCorrectionPopover,
  showActions = false,
  onNodeClick,
  onPlanCorrection,
}: TaskGraphPanelProps) {
  const { Table, Button } = antd;
  const HighlightIcon = createHighlightIcon(React);

  const rows = Object.values(plan.nodes).map((node, index) => ({
    key: node.node_id,
    node_id: node.node_id,
    rowIndex: index + 1,
    name: node.name || node.node_id,
    state: node.state,
  }));

  const columns: Array<Record<string, unknown>> = [
    {
      title: tTaskGraph("taskContent"),
      key: "content",
      render: (_: unknown, record: (typeof rows)[number]) =>
        React.createElement(
          "span",
          { className: "datapaw-task-content" },
          `${record.rowIndex}. ${record.name}`,
        ),
    },
    {
      title: tTaskGraph("taskStatus"),
      key: "state",
      width: STATUS_COL_WIDTH,
      align: "center",
      onHeaderCell: () => ({ className: "datapaw-status-header" }),
      onCell: () => ({ className: "datapaw-status-cell" }),
      render: (_: unknown, record: (typeof rows)[number]) => {
        const config = getStatusConfig(String(record.state ?? ""));
        return React.createElement(
          "span",
          {
            className: `datapaw-status-tag ${config.className}`,
          },
          tTaskGraph(config.labelKey),
        );
      },
    },
  ];

  const actions =
    showActions && PlanCorrectionPopover
      ? React.createElement(
          "div",
          { className: "datapaw-header-actions" },
          React.createElement(
            PlanCorrectionPopover,
            { plan, onConfirm: onPlanCorrection },
            React.createElement(
              Button,
              {
                className: "datapaw-correction-btn",
                icon: React.createElement(HighlightIcon, { size: 14 }),
              },
              tTaskGraph("planCorrection"),
            ),
          ),
        )
      : null;

  return React.createElement(
    "div",
    { className: "datapaw-task-plan", "data-datapaw-task-graph-card": true },
    React.createElement(
      "div",
      { className: "datapaw-task-plan-title" },
      React.createElement(
        "span",
        { className: "datapaw-task-plan-title-text" },
        `${tTaskGraph("planTitle")}：${plan.name}`,
      ),
      actions,
    ),
    React.createElement(Table, {
      className: "datapaw-task-table",
      columns,
      dataSource: rows,
      rowKey: "node_id",
      pagination: false,
      tableLayout: "fixed",
      size: "small",
      scroll: { y: 140 },
      onRow: (record: (typeof rows)[number]) => ({
        onClick: () => {
          if (onNodeClick && isClickable(String(record.state ?? ""))) {
            onNodeClick(record.node_id);
          }
        },
        className:
          onNodeClick && isClickable(String(record.state ?? ""))
            ? "datapaw-clickable-row"
            : undefined,
      }),
    }),
  );
}
