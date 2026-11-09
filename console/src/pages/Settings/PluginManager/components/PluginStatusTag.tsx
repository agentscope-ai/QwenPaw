import type { CSSProperties } from "react";
import { Tag } from "antd";
import { CheckCircle, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { PluginInfo } from "@/api/modules/plugin";

export function PluginStatusTag({
  plugin,
  style,
}: {
  plugin: Pick<PluginInfo, "loaded" | "status">;
  style?: CSSProperties;
}) {
  const { t } = useTranslation();
  const failed = plugin.status === "failed";
  const Icon = !failed && plugin.loaded ? CheckCircle : XCircle;
  const label = failed
    ? "statusError"
    : plugin.loaded
    ? "statusLoaded"
    : "statusUnloaded";

  return (
    <Tag
      icon={<Icon size={12} />}
      color={failed ? "error" : plugin.loaded ? "success" : "default"}
      style={{ display: "inline-flex", alignItems: "center", gap: 4, ...style }}
    >
      {t(`pluginManager.${label}`)}
    </Tag>
  );
}
