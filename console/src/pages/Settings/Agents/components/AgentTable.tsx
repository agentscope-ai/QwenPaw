import { useEffect, useRef, useState } from "react";
import { Table, Button, Space, Popconfirm, Tag, Tooltip, Input } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { DeleteOutlined, RobotOutlined, CopyOutlined } from "@ant-design/icons";
import {
  Check,
  EyeOff,
  Eye,
  PawPrint,
  Pin,
  PinOff,
  SquareTerminal,
  X,
} from "lucide-react";
import type { AgentSummary } from "../../../../api/types/agents";
import { useTheme } from "../../../../contexts/ThemeContext";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { SortableAgentRow, DragHandle } from "./SortableAgentRow";
import { providerIcon } from "../../Models/components/providerIcon";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import styles from "../index.module.less";

const THIRD_PARTY_AGENT_NAMES: Record<string, string> = {
  codex: "Codex",
  qoder: "Qoder",
};

interface AgentTableProps {
  agents: AgentSummary[];
  loading: boolean;
  reordering: boolean;
  onRename: (agentId: string, name: string) => Promise<void>;
  onCopy: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onToggle: (agentId: string, currentEnabled: boolean) => void;
  onPin: (agentId: string, currentPinned: boolean) => void;
  onReorder: (activeId: string, overId: string) => void;
}

export function AgentTable({
  agents,
  loading,
  reordering,
  onRename,
  onCopy,
  onDelete,
  onToggle,
  onPin,
  onReorder,
}: AgentTableProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  // Measure the table's container so the scroll body height follows the
  // actual layout (classic page or OS window) instead of the viewport.
  const containerRef = useRef<HTMLDivElement>(null);
  const [bodyHeight, setBodyHeight] = useState<number>();
  const [renamingAgentId, setRenamingAgentId] = useState<string | null>(null);
  const [renamingName, setRenamingName] = useState("");
  const [savingAgentId, setSavingAgentId] = useState<string | null>(null);
  const [renameError, setRenameError] = useState(false);
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const headerH =
        el.querySelector("thead")?.getBoundingClientRect().height ?? 40;
      const next = el.clientHeight - headerH;
      setBodyHeight(next > 0 ? next : undefined);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 6,
      },
    }),
  );

  const disabledStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.35)", opacity: 1 }
    : {};

  const iconStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.85)" }
    : {};

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }

    onReorder(String(active.id), String(over.id));
  };

  const startRename = (record: AgentSummary) => {
    if (record.id === "default" || savingAgentId) return;
    setRenamingAgentId(record.id);
    setRenamingName(record.name);
    setRenameError(false);
  };

  const cancelRename = () => {
    if (savingAgentId) return;
    setRenamingAgentId(null);
    setRenamingName("");
    setRenameError(false);
  };

  const saveRename = async (record: AgentSummary) => {
    const nextName = renamingName.trim();
    if (!nextName) {
      setRenameError(true);
      return;
    }
    if (nextName === record.name) {
      cancelRename();
      return;
    }

    setSavingAgentId(record.id);
    try {
      await onRename(record.id, nextName);
      setRenamingAgentId(null);
      setRenamingName("");
      setRenameError(false);
    } catch {
      // The parent reports the save error; keep the input open for retry.
    } finally {
      setSavingAgentId(null);
    }
  };

  const columns: ColumnsType<AgentSummary> = [
    {
      title: "",
      key: "sort",
      width: 56,
      align: "center",
      fixed: "left",
      render: (_value: unknown, record: AgentSummary) => (
        <Tooltip title={t("agent.dragHandleTooltip")}>
          <span>
            <DragHandle
              disabled={reordering || loading || record.id === "default"}
            />
          </span>
        </Tooltip>
      ),
    },
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      width: 260,
      fixed: "left",
      render: (_text: string, record: AgentSummary) => (
        <Space>
          <AgentStatusIndicator
            status={record.startup_status}
            enabled={record.enabled}
          />
          <RobotOutlined
            style={{
              fontSize: 16,
              opacity: record.enabled ? 1 : 0.5,
            }}
          />
          {renamingAgentId === record.id ? (
            <Space size={4}>
              <Input
                size="small"
                value={renamingName}
                autoFocus
                status={renameError ? "error" : undefined}
                aria-label={t("agent.name")}
                disabled={savingAgentId === record.id}
                onChange={(event) => {
                  setRenamingName(event.target.value);
                  setRenameError(false);
                }}
                onPressEnter={() => void saveRename(record)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") cancelRename();
                }}
              />
              <Button
                type="text"
                size="small"
                aria-label={t("agent.saveName")}
                title={t("agent.saveName")}
                icon={<Check size={14} />}
                loading={savingAgentId === record.id}
                onClick={() => void saveRename(record)}
              />
              <Button
                type="text"
                size="small"
                aria-label={t("agent.cancelName")}
                title={t("agent.cancelName")}
                icon={<X size={14} />}
                disabled={savingAgentId === record.id}
                onClick={cancelRename}
              />
            </Space>
          ) : (
            <Space size={6}>
              <span style={{ opacity: record.enabled ? 1 : 0.5 }}>
                {getAgentDisplayName(record, t)}
              </span>
              {record.id !== "default" && (
                <Button
                  type="link"
                  size="small"
                  className={styles.agentNameEditButton}
                  aria-label={t("agent.editName")}
                  onClick={() => startRename(record)}
                  disabled={Boolean(savingAgentId)}
                >
                  {t("agent.editName")}
                </Button>
              )}
            </Space>
          )}
          {(record.id === "default" || record.pinned) && (
            <Pin size={13} aria-label={t("agent.pinned")} />
          )}
        </Space>
      ),
    },
    {
      title: t("agent.id"),
      dataIndex: "id",
      key: "id",
      width: 180,
    },
    {
      title: t("agent.backend.column"),
      dataIndex: "backend",
      key: "backend",
      width: 180,
      render: (backend: AgentSummary["backend"]) => {
        const thirdParty = backend !== "qwenpaw";
        const name = THIRD_PARTY_AGENT_NAMES[backend] ?? backend;
        return (
          <Tag
            className={`${styles.backendTag} ${
              thirdParty ? styles.backendTagThirdParty : ""
            }`}
            icon={
              thirdParty ? <SquareTerminal size={12} /> : <PawPrint size={12} />
            }
          >
            {thirdParty
              ? `${name} · ${t("agent.backend.thirdPartyBadge")}`
              : `QwenPaw · ${t("agent.backend.nativeBadge")}`}
          </Tag>
        );
      },
    },
    {
      title: t("agent.description"),
      dataIndex: "description",
      key: "description",
      width: 220,
      ellipsis: true,
    },
    {
      title: t("agent.workspace"),
      dataIndex: "workspace_dir",
      key: "workspace_dir",
      width: 260,
      ellipsis: true,
    },
    {
      title: t("agent.modelColumn"),
      key: "active_model",
      width: 220,
      ellipsis: true,
      render: (_value: unknown, record: AgentSummary) => {
        if (record.backend !== "qwenpaw") {
          const model = record.backend_model;
          return model ? (
            <Space size={6}>
              <SquareTerminal size={15} />
              <Tooltip
                title={
                  record.backend_reasoning_effort
                    ? `${model} · ${record.backend_reasoning_effort}`
                    : model
                }
              >
                <span>{model}</span>
              </Tooltip>
            </Space>
          ) : (
            <span style={{ opacity: 0.45 }}>
              {t("agent.backend.modelDefault")}
            </span>
          );
        }
        if (!record.active_model) {
          return (
            <span style={{ opacity: 0.45 }}>{t("agent.modelPlaceholder")}</span>
          );
        }
        return (
          <Space size={6}>
            <img
              src={providerIcon(record.active_model.provider_id)}
              alt=""
              style={{ width: 16, height: 16 }}
            />
            <Tooltip title={record.active_model.model}>
              <span>{record.active_model.model}</span>
            </Tooltip>
          </Space>
        );
      },
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 240,
      fixed: "right",
      render: (_value: unknown, record: AgentSummary) => {
        const startupInProgress =
          record.startup_status === "pending" ||
          record.startup_status === "starting";
        const toggleDisabled = record.id === "default" || startupInProgress;
        const pinActionLabel =
          record.id === "default"
            ? t("agent.defaultPinned")
            : record.pinned
            ? t("agent.unpinAgent")
            : t("agent.pinAgent");

        return (
          <Space>
            <Tooltip title={pinActionLabel}>
              <Button
                type="text"
                size="middle"
                aria-label={pinActionLabel}
                icon={
                  record.id === "default" || record.pinned ? (
                    <Pin size={14} />
                  ) : (
                    <PinOff size={14} />
                  )
                }
                onClick={() => onPin(record.id, Boolean(record.pinned))}
                disabled={record.id === "default"}
                style={record.id === "default" ? disabledStyle : iconStyle}
              />
            </Tooltip>
            <Button
              type="text"
              size="middle"
              icon={<CopyOutlined />}
              onClick={() => onCopy(record)}
              style={iconStyle}
              title={
                record.id === "default"
                  ? t("agent.copyDefaultTooltip")
                  : t("agent.copyTooltip")
              }
            />
            <Popconfirm
              title={
                record.enabled
                  ? t("agent.disableConfirm")
                  : t("agent.enableConfirm")
              }
              description={
                record.enabled
                  ? t("agent.disableConfirmDesc")
                  : t("agent.enableConfirmDesc")
              }
              onConfirm={() => onToggle(record.id, record.enabled)}
              disabled={toggleDisabled}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="text"
                size="middle"
                icon={record.enabled ? <EyeOff size={14} /> : <Eye size={14} />}
                disabled={toggleDisabled}
                style={record.id === "default" ? disabledStyle : iconStyle}
                title={
                  record.id === "default"
                    ? t("agent.defaultNotDisablable")
                    : startupInProgress
                    ? t("agent.status.waitUntilStarted")
                    : undefined
                }
              />
            </Popconfirm>
            <Popconfirm
              title={t("agent.deleteConfirm")}
              description={t("agent.deleteConfirmDesc")}
              onConfirm={() => onDelete(record.id)}
              disabled={toggleDisabled}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Button
                type="link"
                size="middle"
                danger
                icon={<DeleteOutlined />}
                disabled={toggleDisabled}
                style={record.id === "default" ? disabledStyle : undefined}
                title={
                  record.id === "default"
                    ? t("agent.defaultNotDeletable")
                    : startupInProgress
                    ? t("agent.status.waitUntilStarted")
                    : undefined
                }
              />
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext
        items={agents.map((agent) => agent.id)}
        strategy={verticalListSortingStrategy}
      >
        <div
          ref={containerRef}
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <Table
            dataSource={agents}
            columns={columns}
            loading={loading}
            rowKey="id"
            components={{
              body: {
                row: SortableAgentRow,
              },
            }}
            pagination={false}
            scroll={{ x: 1620, y: bodyHeight }}
          />
        </div>
      </SortableContext>
    </DndContext>
  );
}
