import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { Pencil, Trash2, EyeOff, Eye, Bot, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AgentSummary } from "../../../../api/types/agents";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { SortableAgentRow, DragHandle } from "./SortableAgentRow";
import { providerIcon } from "../../Models/components/providerIcon";
import styles from "../index.module.less";

interface AgentTableProps {
  agents: AgentSummary[];
  loading: boolean;
  reordering: boolean;
  onEdit: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onToggle: (agentId: string, currentEnabled: boolean) => void;
  onReorder: (activeId: string, overId: string) => void;
}

interface ConfirmState {
  type: "toggle" | "delete";
  agent: AgentSummary;
}

export function AgentTable({
  agents,
  loading,
  reordering,
  onEdit,
  onDelete,
  onToggle,
  onReorder,
}: AgentTableProps) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    onReorder(String(active.id), String(over.id));
  };

  const handleConfirm = () => {
    if (!confirm) return;
    if (confirm.type === "toggle") {
      onToggle(confirm.agent.id, confirm.agent.enabled);
    } else {
      onDelete(confirm.agent.id);
    }
    setConfirm(null);
  };

  const confirmTitle = confirm
    ? confirm.type === "delete"
      ? t("agent.deleteConfirm")
      : confirm.agent.enabled
      ? t("agent.disableConfirm")
      : t("agent.enableConfirm")
    : "";

  const confirmDesc = confirm
    ? confirm.type === "delete"
      ? t("agent.deleteConfirmDesc")
      : confirm.agent.enabled
      ? t("agent.disableConfirmDesc")
      : t("agent.enableConfirmDesc")
    : "";

  return (
    <div className={styles.tableCard}>
      {(loading || reordering) && (
        <div className="flex items-center gap-2 mb-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          {t("common.loading")}
        </div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={agents.map((a) => a.id)}
          strategy={verticalListSortingStrategy}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead className="w-64">{t("agent.name")}</TableHead>
                <TableHead>{t("agent.id")}</TableHead>
                <TableHead>{t("agent.description")}</TableHead>
                <TableHead>{t("agent.workspace")}</TableHead>
                <TableHead className="w-60">{t("agent.modelColumn")}</TableHead>
                <TableHead className="w-32">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.map((agent) => (
                <SortableAgentRow key={agent.id} id={agent.id}>
                  <TableCell className="w-10">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>
                          <DragHandle disabled={reordering || loading} />
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {t("agent.dragHandleTooltip")}
                      </TooltipContent>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Bot
                        size={16}
                        className={agent.enabled ? "" : "opacity-50"}
                      />
                      <span
                        className={agent.enabled ? "" : "opacity-50 text-sm"}
                      >
                        {getAgentDisplayName(agent, t)}
                      </span>
                      {!agent.enabled && (
                        <Badge variant="destructive" className="text-xs">
                          {t("agent.disabled")}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {agent.id}
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate text-sm text-muted-foreground">
                    {agent.description}
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate text-sm text-muted-foreground">
                    {agent.workspace_dir}
                  </TableCell>
                  <TableCell>
                    {agent.active_model ? (
                      <div className="flex items-center gap-1.5">
                        <img
                          src={providerIcon(agent.active_model.provider_id)}
                          alt=""
                          className="w-4 h-4"
                        />
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="text-sm truncate max-w-[180px] block">
                              {agent.active_model.model}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            {agent.active_model.model}
                          </TooltipContent>
                        </Tooltip>
                      </div>
                    ) : (
                      <span className="text-sm opacity-45">
                        {t("agent.modelPlaceholder")}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => onEdit(agent)}
                            disabled={agent.id === "default"}
                            title={
                              agent.id === "default"
                                ? t("agent.defaultNotEditable")
                                : undefined
                            }
                          >
                            <Pencil size={14} />
                          </Button>
                        </TooltipTrigger>
                        {agent.id !== "default" && (
                          <TooltipContent>{t("common.edit")}</TooltipContent>
                        )}
                      </Tooltip>

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() =>
                              setConfirm({ type: "toggle", agent })
                            }
                            disabled={agent.id === "default"}
                            title={
                              agent.id === "default"
                                ? t("agent.defaultNotDisablable")
                                : undefined
                            }
                          >
                            {agent.enabled ? (
                              <EyeOff size={14} />
                            ) : (
                              <Eye size={14} />
                            )}
                          </Button>
                        </TooltipTrigger>
                        {agent.id !== "default" && (
                          <TooltipContent>
                            {agent.enabled
                              ? t("agent.disableConfirm")
                              : t("agent.enableConfirm")}
                          </TooltipContent>
                        )}
                      </Tooltip>

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-destructive hover:text-destructive"
                            onClick={() =>
                              setConfirm({ type: "delete", agent })
                            }
                            disabled={agent.id === "default"}
                            title={
                              agent.id === "default"
                                ? t("agent.defaultNotDeletable")
                                : undefined
                            }
                          >
                            <Trash2 size={14} />
                          </Button>
                        </TooltipTrigger>
                        {agent.id !== "default" && (
                          <TooltipContent>{t("common.delete")}</TooltipContent>
                        )}
                      </Tooltip>
                    </div>
                  </TableCell>
                </SortableAgentRow>
              ))}
            </TableBody>
          </Table>
        </SortableContext>
      </DndContext>

      <AlertDialog
        open={!!confirm}
        onOpenChange={(o) => {
          if (!o) setConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>{confirmDesc}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setConfirm(null)}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirm}>
              {t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
