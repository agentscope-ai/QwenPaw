import { useEffect, useMemo, useRef, useState } from "react";
import { Empty, Tag, Tooltip } from "antd";
import { GitBranch, GitCommitHorizontal } from "lucide-react";
import { FixedSizeList, type ListChildComponentProps } from "react-window";
import { useTranslation } from "react-i18next";
import type { CheckpointNode } from "@/api/types/checkpoints";
import type { GraphRow } from "./graphLayout";
import styles from "./index.module.less";

const ROW_HEIGHT = 58;
const LANE_GAP = 18;
const LANE_START = 15;
const COLORS = [
  "#3178c6",
  "#2d8a68",
  "#b26a1b",
  "#8b5fbf",
  "#c34f67",
  "#3b8793",
];

function stableColor(value: string): string {
  let hash = 0;
  for (let i = 0; i < value.length; i++)
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  return COLORS[Math.abs(hash) % COLORS.length];
}

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () =>
      setSize({ width: element.clientWidth, height: element.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, size };
}

interface RowData {
  rows: GraphRow[];
  graphWidth: number;
  selectedCommit: string | null;
  onSelect: (node: CheckpointNode) => void;
  colors: Map<string, string>;
  locale: string;
  labels: Record<string, string>;
}

function GraphLines({
  row,
  width,
  colors,
}: {
  row: GraphRow;
  width: number;
  colors: Map<string, string>;
}) {
  const x = (lane: number) => LANE_START + lane * LANE_GAP;
  const center = ROW_HEIGHT / 2;
  const nodeColor = stableColor(row.node.session_key);
  return (
    <svg
      className={styles.graphSvg}
      width={width}
      height={ROW_HEIGHT}
      aria-hidden="true"
    >
      {row.lanesBefore.map(
        (commit, lane) =>
          commit && (
            <line
              key={`top-${lane}`}
              x1={x(lane)}
              y1={0}
              x2={x(lane)}
              y2={center}
              stroke={colors.get(commit) ?? nodeColor}
            />
          ),
      )}
      {row.lanesAfter.map(
        (commit, lane) =>
          commit && (
            <line
              key={`bottom-${lane}`}
              x1={x(lane)}
              y1={center}
              x2={x(lane)}
              y2={ROW_HEIGHT}
              stroke={colors.get(commit) ?? nodeColor}
            />
          ),
      )}
      {row.parentLane !== null && row.parentLane !== row.lane && (
        <path
          d={`M ${x(row.lane)} ${center} C ${x(row.lane)} ${center + 13}, ${x(
            row.parentLane,
          )} ${center + 13}, ${x(row.parentLane)} ${ROW_HEIGHT}`}
          stroke={nodeColor}
          fill="none"
        />
      )}
      {row.node.is_head && (
        <circle
          className={styles.headHalo}
          cx={x(row.lane)}
          cy={center}
          r={9}
          fill="none"
          stroke={nodeColor}
        />
      )}
      {row.node.kind === "snap" ? (
        <rect
          className={styles.snapshotNode}
          x={x(row.lane) - 5}
          y={center - 5}
          width={10}
          height={10}
          rx={1}
          fill={nodeColor}
        />
      ) : (
        <circle
          cx={x(row.lane)}
          cy={center}
          r={row.node.kind === "pre-restore" ? 5.5 : 4.5}
          fill={
            row.node.kind === "pre-restore"
              ? "var(--checkpoint-surface)"
              : nodeColor
          }
          stroke={nodeColor}
          strokeWidth={row.node.kind === "pre-restore" ? 2.5 : 2}
        />
      )}
    </svg>
  );
}

function VirtualRow({ index, style, data }: ListChildComponentProps<RowData>) {
  const { rows, graphWidth, selectedCommit, onSelect, colors, locale, labels } =
    data;
  const row = rows[index];
  const node = row.node;
  const title = node.query || node.name || node.subject;
  const kindLabel = labels[node.kind] ?? node.kind;
  return (
    <button
      type="button"
      className={`${styles.graphRow} ${
        selectedCommit === node.commit ? styles.selectedRow : ""
      }`}
      style={style}
      onClick={() => onSelect(node)}
      aria-label={`${title}, ${kindLabel}`}
    >
      <div className={styles.graphCell} style={{ width: graphWidth }}>
        <GraphLines row={row} width={graphWidth} colors={colors} />
      </div>
      <div className={styles.messageCell}>
        <span className={styles.messageTitle}>{title}</span>
        <span className={styles.messageMeta}>
          {node.channel} ·{" "}
          {node.session_title || node.session_id || node.session_key}
        </span>
      </div>
      <div className={styles.kindCell}>
        {node.is_head && (
          <span className={styles.headTag}>
            <GitBranch size={11} />
            HEAD
          </span>
        )}
        <Tag
          bordered={false}
          className={`${styles.kindTag} ${
            styles[`kind_${node.kind.replace("-", "_")}`]
          }`}
        >
          {kindLabel}
        </Tag>
      </div>
      <Tooltip title={node.commit} mouseEnterDelay={0.5}>
        <code className={styles.shaCell}>{node.sha}</code>
      </Tooltip>
      <time
        className={styles.timeCell}
        dateTime={new Date(node.timestamp_ms).toISOString()}
      >
        {new Intl.DateTimeFormat(locale, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }).format(node.timestamp_ms)}
      </time>
    </button>
  );
}

interface CheckpointGraphProps {
  rows: GraphRow[];
  laneCount: number;
  selectedCommit: string | null;
  onSelect: (node: CheckpointNode) => void;
  emptyDescription: string;
}

export function CheckpointGraph({
  rows,
  laneCount,
  selectedCommit,
  onSelect,
  emptyDescription,
}: CheckpointGraphProps) {
  const { t, i18n } = useTranslation();
  const { ref, size } = useElementSize<HTMLDivElement>();
  const graphWidth = Math.max(
    72,
    Math.min(224, LANE_START * 2 + laneCount * LANE_GAP),
  );
  const colors = useMemo(
    () =>
      new Map(
        rows.map(({ node }) => [node.commit, stableColor(node.session_key)]),
      ),
    [rows],
  );
  const labels = useMemo(
    () => ({
      auto: t("checkpoints.kind.auto"),
      snap: t("checkpoints.kind.snapshot"),
      "pre-restore": t("checkpoints.kind.safety"),
      sha: t("checkpoints.kind.commit"),
    }),
    [t],
  );
  const data = useMemo<RowData>(
    () => ({
      rows,
      graphWidth,
      selectedCommit,
      onSelect,
      colors,
      locale: i18n.resolvedLanguage || "en",
      labels,
    }),
    [
      rows,
      graphWidth,
      selectedCommit,
      onSelect,
      colors,
      i18n.resolvedLanguage,
      labels,
    ],
  );

  return (
    <div className={styles.graphPanel}>
      <div className={styles.graphHeader}>
        <span style={{ width: graphWidth }}>
          <GitCommitHorizontal size={15} /> {t("checkpoints.graph")}
        </span>
        <span className={styles.messageHeader}>
          {t("checkpoints.checkpoint")}
        </span>
        <span>{t("checkpoints.type")}</span>
        <span>{t("checkpoints.commit")}</span>
        <span>{t("checkpoints.createdAt")}</span>
      </div>
      <div ref={ref} className={styles.graphBody}>
        {!rows.length ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={emptyDescription}
            className={styles.emptyState}
          />
        ) : size.width > 0 && size.height > 0 ? (
          <FixedSizeList
            height={size.height}
            width={size.width}
            itemCount={rows.length}
            itemSize={ROW_HEIGHT}
            itemData={data}
            itemKey={(index, itemData) => itemData.rows[index].node.ref}
            overscanCount={8}
          >
            {VirtualRow}
          </FixedSizeList>
        ) : null}
      </div>
    </div>
  );
}
