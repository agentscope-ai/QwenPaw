import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Package, Trash2, CheckCircle, XCircle } from "lucide-react";
import type { PluginType, PluginInfo } from "@/api/modules/plugin";
import { PluginTypeTag } from "../components/PluginTypeTag";

interface UsePluginColumnsOptions {
  uninstallingId: string | null;
  onUninstall: (record: PluginInfo) => void;
}

export function usePluginColumns({
  uninstallingId,
  onUninstall,
}: UsePluginColumnsOptions) {
  const { t } = useTranslation();

  return [
    {
      title: t("pluginManager.title"),
      dataIndex: "name",
      key: "name",
      render: (name: string, record: PluginInfo) => (
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <Package size={16} style={{ flexShrink: 0 }} />
            <span className="font-medium">{name}</span>
          </div>
          {record.description && (
            <span className="text-xs text-muted-foreground">
              {record.description}
            </span>
          )}
        </div>
      ),
    },
    {
      title: t("pluginManager.type"),
      dataIndex: "plugin_type",
      key: "plugin_type",
      width: 110,
      render: (type: PluginType) => <PluginTypeTag type={type ?? "general"} />,
    },
    {
      title: t("pluginManager.version"),
      dataIndex: "version",
      key: "version",
      width: 100,
      render: (version: string) => (
        <span className="text-xs text-muted-foreground">{version}</span>
      ),
    },
    {
      title: t("pluginManager.author"),
      dataIndex: "author",
      key: "author",
      width: 140,
      render: (author: string) => (
        <span className="text-xs text-muted-foreground">
          {author || t("pluginManager.unknown")}
        </span>
      ),
    },
    {
      title: "Status",
      dataIndex: "loaded",
      key: "loaded",
      width: 110,
      render: (loaded: boolean) =>
        loaded ? (
          <Badge
            variant="outline"
            className="inline-flex items-center gap-1 text-xs text-green-600 border-green-300"
          >
            <CheckCircle size={12} />
            {t("pluginManager.statusLoaded")}
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground"
          >
            <XCircle size={12} />
            {t("pluginManager.statusUnloaded")}
          </Badge>
        ),
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, record: PluginInfo) => (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-destructive hover:text-destructive"
              disabled={uninstallingId === record.id}
              onClick={() => onUninstall(record)}
            >
              <Trash2 size={14} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("pluginManager.uninstall")}</TooltipContent>
        </Tooltip>
      ),
    },
  ];
}
