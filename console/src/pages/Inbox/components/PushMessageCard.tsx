import { useState } from "react";
import {
  MessageCircle,
  Hash,
  Send,
  MessageSquare,
  Mail,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import type { PushMessage } from "../types";

interface PushMessageCardProps {
  message: PushMessage;
  onMarkAsRead: (id: string) => void;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
  selected?: boolean;
  onSelectChange?: (id: string, checked: boolean) => void;
}

const CHANNEL_ICONS = {
  wechat: MessageCircle,
  slack: Hash,
  telegram: Send,
  discord: MessageSquare,
  email: Mail,
  heartbeat: MessageCircle,
};

const CHANNEL_COLORS: Record<string, string> = {
  wechat: "#07C160",
  slack: "#4A154B",
  telegram: "#0088CC",
  discord: "#5865F2",
  email: "#EA4335",
  heartbeat: "#5865F2",
};

const normalizeCronTaskName = (title: string): string =>
  title
    .replace(/^(cron result|heartbeat result)\s*[:：]\s*/i, "")
    .replace(/^(定时任务结果|心跳结果)\s*[:：]\s*/i, "")
    .trim();

export function PushMessageCard(props: PushMessageCardProps) {
  const { message, onView, onDelete, selected = false, onSelectChange } = props;
  const { t } = useTranslation();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const IconComponent = CHANNEL_ICONS[message.channelType];
  const channelColor = CHANNEL_COLORS[message.channelType] ?? "#888";
  const sourceType = (message.metadata?.sourceType || "").toLowerCase();
  const isCronMessage = sourceType === "cron";
  const displayTitle = isCronMessage
    ? t("inbox.pushCronHeader", { name: normalizeCronTaskName(message.title) })
    : message.title;

  const priority = message.metadata?.priority;
  const showPriorityBadge = priority && priority !== "normal";

  return (
    <Card
      className={cn(
        "cursor-pointer hover:shadow-md transition-shadow rounded-[10px] shadow-sm",
        !message.read && "border-l-2 border-l-orange-400",
      )}
      onClick={() => onView(message.id)}
    >
      <CardContent className="p-3.5 flex flex-col gap-0">
        <div className="flex justify-between items-start gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            {onSelectChange && (
              <Checkbox
                checked={selected}
                onCheckedChange={(checked) => {
                  onSelectChange(message.id, Boolean(checked));
                }}
                onClick={(event) => event.stopPropagation()}
                className="shrink-0"
              />
            )}
            <Avatar
              className="w-9 h-9 shrink-0"
              style={{ backgroundColor: channelColor }}
            >
              <AvatarFallback
                className="text-white"
                style={{ backgroundColor: channelColor }}
              >
                <IconComponent size={18} />
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground truncate">
                {message.channelName}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {t("inbox.from")} {message.sender.username}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {!message.read && (
              <span className="w-2 h-2 rounded-full bg-orange-400 shrink-0" />
            )}
            {showPriorityBadge && (
              <Badge
                variant={priority === "urgent" ? "destructive" : "secondary"}
                className={cn(
                  "text-[11px] font-semibold border-0",
                  priority === "high" &&
                    "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400",
                )}
              >
                {priority.toUpperCase()}
              </Badge>
            )}
            <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-destructive hover:bg-destructive/10 hover:text-destructive shrink-0"
                  onClick={(event) => {
                    event.stopPropagation();
                    setDeleteOpen(true);
                  }}
                >
                  <Trash2 size={14} />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                <AlertDialogHeader>
                  <AlertDialogTitle>
                    {t("inbox.deleteMessageConfirm")}
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    {t(
                      "common.actionCannotBeUndone",
                      "This action cannot be undone.",
                    )}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel onClick={(e) => e.stopPropagation()}>
                    {t("common.cancel")}
                  </AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-destructive text-white hover:bg-destructive/90"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(message.id);
                      setDeleteOpen(false);
                    }}
                  >
                    {t("common.confirm")}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
        <div className="mt-3">
          <h4 className="text-sm font-semibold text-foreground mb-1 leading-snug">
            {displayTitle}
          </h4>
          <p className="text-sm text-muted-foreground leading-relaxed line-clamp-2">
            {message.content}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
