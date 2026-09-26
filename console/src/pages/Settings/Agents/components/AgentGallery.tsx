import ReactMarkdown from "react-markdown";
import { useMemoizedFn } from "ahooks";
import { memo, useState, useMemo } from "react";
import { Button, Empty, Popconfirm, Spin } from "antd";
import {
  GripVertical,
  Pin,
  Copy,
  Pencil,
  Power,
  Trash2,
  ChevronRight,
} from "lucide-react";
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { useTranslation } from "react-i18next";
import { SharedModal } from "@/components/interaction/SharedModal";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { AgentSummary } from "@/api/types/agents";
import styles from "./AgentGallery.module.less";

interface AgentGalleryProps {
  agents: AgentSummary[];
  loading: boolean;
  reordering: boolean;
  onEdit: (agent: AgentSummary) => void;
  onCopy: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onToggle: (agentId: string, currentEnabled: boolean) => void;
  onPin: (agentId: string, currentPinned: boolean) => void;
  onReorder: (activeId: string, overId: string) => void;
}

const autoScrollOptions = { interval: 16 };
const pointerSensorOptions = { activationConstraint: { distance: 6 } };
const keyboardSensorOptions = { coordinateGetter: sortableKeyboardCoordinates };

const AgentTile = memo(function AgentTile({
  agent,
  disabled,
  onOpen,
  onPin,
  onEdit,
  onCopy,
  onToggle,
}: {
  agent: AgentSummary;
  disabled: boolean;
  onOpen: (agentId: string) => void;
  onPin: AgentGalleryProps["onPin"];
  onEdit: AgentGalleryProps["onEdit"];
  onCopy: AgentGalleryProps["onCopy"];
  onToggle: AgentGalleryProps["onToggle"];
}) {
  const { t } = useTranslation();
  const locked =
    disabled ||
    agent.id === "default" ||
    ["pending", "starting"].includes(agent.startup_status ?? "");
  const sortable = useSortable({
    id: agent.id,
    disabled: disabled || agent.id === "default",
  });
  const content = useMemo(
    () => (
      <article
        className={styles.card}
        style={{ borderRadius: 12 }}
        data-dragging={sortable.isDragging || undefined}
      >
        <div className={styles.top}>
          <AgentStatusIndicator
            status={agent.startup_status}
            enabled={agent.enabled}
          />
          <span>{agent.backend === "qwenpaw" ? "QwenPaw" : agent.backend}</span>
          <Button
            type="text"
            aria-label={t(agent.pinned ? "agent.unpinAgent" : "agent.pinAgent")}
            disabled={agent.id === "default"}
            onClick={() => onPin(agent.id, !!agent.pinned)}
            icon={
              <Pin
                size={15}
                fill={
                  agent.pinned || agent.id === "default"
                    ? "currentColor"
                    : "none"
                }
              />
            }
          />
          <button
            className={styles.drag}
            type="button"
            {...sortable.attributes}
            {...sortable.listeners}
            disabled={disabled || agent.id === "default"}
            aria-label={t("agent.dragHandleTooltip")}
          >
            <GripVertical size={18} />
          </button>
        </div>
        <button
          type="button"
          className={styles.open}
          onClick={() => onOpen(agent.id)}
        >
          <strong>{getAgentDisplayName(agent, t)}</strong>
          <span>
            {agent.backend === "qwenpaw"
              ? agent.active_model?.model || t("agent.modelPlaceholder")
              : agent.backend_model || agent.backend}
          </span>
          <span className={styles.identity}>
            <code>{agent.id}</code>
            <ChevronRight size={18} />
          </span>
        </button>
        <div className={styles.quickActions}>
          <Button
            type="text"
            aria-label={t("common.edit")}
            title={t("common.edit")}
            disabled={disabled || agent.id === "default"}
            icon={<Pencil size={16} />}
            onClick={() => onEdit(agent)}
          />
          <Button
            type="text"
            aria-label={t("common.copy")}
            title={t("common.copy")}
            disabled={disabled}
            icon={<Copy size={16} />}
            onClick={() => onCopy(agent)}
          />
          <Popconfirm
            title={t(
              agent.enabled ? "agent.disableConfirm" : "agent.enableConfirm",
            )}
            description={t(
              agent.enabled
                ? "agent.disableConfirmDesc"
                : "agent.enableConfirmDesc",
            )}
            disabled={locked}
            onConfirm={() => onToggle(agent.id, agent.enabled)}
          >
            <Button
              type="text"
              disabled={locked}
              icon={<Power size={16} />}
              aria-label={t(agent.enabled ? "common.disable" : "common.enable")}
              title={t(agent.enabled ? "common.disable" : "common.enable")}
            />
          </Popconfirm>
        </div>
      </article>
    ),
    [
      agent,
      disabled,
      locked,
      onCopy,
      onEdit,
      onOpen,
      onPin,
      onToggle,
      sortable.attributes,
      sortable.listeners,
      sortable.isDragging,
      t,
    ],
  );
  return (
    <div
      ref={sortable.setNodeRef}
      style={{
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
        zIndex: sortable.isDragging ? 2 : undefined,
        willChange: sortable.isDragging ? "transform" : undefined,
      }}
    >
      {content}
    </div>
  );
});

export function AgentGallery(props: AgentGalleryProps) {
  const {
    agents,
    loading,
    onEdit,
    onCopy,
    onDelete,
    onToggle,
    onPin,
    onReorder,
  } = props;
  // Keep row content memoized when the parent updates the local order.
  const editAgent = useMemoizedFn(onEdit);
  const copyAgent = useMemoizedFn(onCopy);
  const pinAgent = useMemoizedFn(onPin);
  const toggleAgent = useMemoizedFn(onToggle);
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string | null>(null);
  const agent = agents.find((item) => item.id === selected);
  const sensors = useSensors(
    useSensor(PointerSensor, pointerSensorOptions),
    useSensor(KeyboardSensor, keyboardSensorOptions),
  );
  const locked =
    !agent ||
    agent.id === "default" ||
    agent.startup_status === "pending" ||
    agent.startup_status === "starting";
  return (
    <>
      <Spin spinning={loading}>
        <DndContext
          sensors={sensors}
          autoScroll={autoScrollOptions}
          collisionDetection={closestCenter}
          onDragEnd={({ active, over }) => {
            if (over && active.id !== over.id)
              onReorder(String(active.id), String(over.id));
          }}
        >
          <SortableContext
            items={agents.map((item) => item.id)}
            strategy={verticalListSortingStrategy}
          >
            <div className={styles.grid}>
              {agents.map((item) => (
                <AgentTile
                  key={item.id}
                  agent={item}
                  disabled={loading}
                  onOpen={setSelected}
                  onPin={pinAgent}
                  onEdit={editAgent}
                  onCopy={copyAgent}
                  onToggle={toggleAgent}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
        {!loading && !agents.length && <Empty />}
      </Spin>
      <SharedModal
        open={!!agent}
        surfaceId={agent ? `agent-detail:${agent.id}` : undefined}
        title={agent ? getAgentDisplayName(agent, t) : ""}
        onCancel={() => setSelected(null)}
        footer={null}
      >
        {agent && (
          <>
            <div className={styles.description}>
              <ReactMarkdown>{agent.description}</ReactMarkdown>
            </div>
            <dl className={styles.details}>
              <dt>{t("agent.id")}</dt>
              <dd>{agent.id}</dd>
              <dt>{t("agent.backend.column")}</dt>
              <dd>{agent.backend}</dd>
              <dt>{t("agent.workspace")}</dt>
              <dd>{agent.workspace_dir}</dd>
              <dt>{t("agent.modelColumn")}</dt>
              <dd>
                {agent.active_model?.model ||
                  agent.backend_model ||
                  t("agent.modelPlaceholder")}
              </dd>
            </dl>
            <div className={styles.actions}>
              <Button
                type="primary"
                icon={<Pencil size={16} />}
                disabled={agent.id === "default"}
                onClick={() => {
                  setSelected(null);
                  onEdit(agent);
                }}
              >
                {t("common.edit")}
              </Button>
              <Button
                icon={<Copy size={16} />}
                onClick={() => {
                  setSelected(null);
                  onCopy(agent);
                }}
              >
                {t("common.copy")}
              </Button>
              <Popconfirm
                title={t(
                  agent.enabled
                    ? "agent.disableConfirm"
                    : "agent.enableConfirm",
                )}
                description={t(
                  agent.enabled
                    ? "agent.disableConfirmDesc"
                    : "agent.enableConfirmDesc",
                )}
                onConfirm={() => onToggle(agent.id, agent.enabled)}
                disabled={locked}
              >
                <Button disabled={locked} icon={<Power size={16} />}>
                  {t(agent.enabled ? "common.disable" : "common.enable")}
                </Button>
              </Popconfirm>
              <Popconfirm
                title={t("agent.deleteConfirm")}
                description={t("agent.deleteConfirmDesc")}
                onConfirm={() => {
                  onDelete(agent.id);
                  setSelected(null);
                }}
                disabled={locked}
              >
                <Button danger disabled={locked} icon={<Trash2 size={16} />}>
                  {t("common.delete")}
                </Button>
              </Popconfirm>
            </div>
          </>
        )}
      </SharedModal>
    </>
  );
}
