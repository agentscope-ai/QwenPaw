import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { ColumnDef } from "@tanstack/react-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatTime, type Session } from "./constants";
import { CHANNEL_COLORS } from "../../../../constants/channel";

interface ColumnHandlers {
  onEdit: (session: Session) => void;
  onDelete: (sessionId: string) => void;
  onView: (session: Session) => void;
  t: TFunction;
}

/** Normalize ISO string to UTC for consistent sorting across mixed timezone formats. */
const toUTCTime = (ts: string | null | undefined): number => {
  if (!ts) return 0;
  const normalized =
    /[Z+\-]\d{2}:?\d{2}$/.test(ts) || ts.endsWith("Z") ? ts : ts + "Z";
  return new Date(normalized).getTime();
};

// Map CHANNEL_COLORS values to Badge variant classes
function channelBadgeClass(channel: string): string {
  const color = CHANNEL_COLORS[channel];
  if (!color || color === "default") return "";
  return "";
}

export const createColumns = (
  handlers: ColumnHandlers,
): ColumnDef<Session>[] => {
  const { t } = useTranslation();

  return [
    {
      accessorKey: "id",
      header: "ID",
      size: 250,
    },
    {
      accessorKey: "name",
      header: "Name",
      size: 200,
    },
    {
      accessorKey: "session_id",
      header: "SessionID",
      size: 180,
    },
    {
      accessorKey: "user_id",
      header: "UserID",
      size: 150,
    },
    {
      accessorKey: "channel",
      header: "Channel",
      size: 120,
      cell: ({ row }) => {
        const channel: string = row.getValue("channel");
        return (
          <Badge variant="secondary" className={channelBadgeClass(channel)}>
            {channel}
          </Badge>
        );
      },
    },
    {
      accessorKey: "created_at",
      header: "CreatedAt",
      size: 180,
      cell: ({ row }) => formatTime(row.getValue("created_at")),
      sortingFn: (a, b) =>
        toUTCTime(a.original.created_at) - toUTCTime(b.original.created_at),
    },
    {
      accessorKey: "updated_at",
      header: "UpdatedAt",
      size: 180,
      cell: ({ row }) => formatTime(row.getValue("updated_at")),
      sortingFn: (a, b) =>
        toUTCTime(a.original.updated_at) - toUTCTime(b.original.updated_at),
    },
    {
      id: "action",
      header: "Action",
      size: 180,
      cell: ({ row }) => {
        const record = row.original;
        return (
          <div className="flex items-center gap-1">
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => handlers.onEdit(record)}
            >
              {t("common.edit")}
            </Button>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs text-green-600"
              onClick={() => handlers.onView(record)}
            >
              {t("common.view")}
            </Button>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs text-destructive"
              onClick={() => handlers.onDelete(record.id)}
            >
              {t("common.delete")}
            </Button>
          </div>
        );
      },
    },
  ];
};
