import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  Package,
  Wrench,
  BrainCircuit,
  Zap,
  Terminal,
  LayoutDashboard,
  AppWindow,
} from "lucide-react";
import { SparkWifiLine } from "@agentscope-ai/icons";
import type { PluginType } from "@/api/modules/plugin";

const PLUGIN_TYPE_CONFIG: Record<
  PluginType,
  { label: string; color: string; icon: React.ReactNode }
> = {
  tool: {
    label: "Tool",
    color: "blue",
    icon: <Wrench size={11} />,
  },
  provider: {
    label: "Provider",
    color: "purple",
    icon: <BrainCircuit size={11} />,
  },
  hook: {
    label: "Hook",
    color: "orange",
    icon: <Zap size={11} />,
  },
  command: {
    label: "Command",
    color: "cyan",
    icon: <Terminal size={11} />,
  },
  frontend: {
    label: "Frontend",
    color: "green",
    icon: <LayoutDashboard size={11} />,
  },
  app: {
    label: "App",
    color: "geekblue",
    icon: <AppWindow size={11} />,
  },
  channel: {
    label: "Channel",
    color: "default",
    icon: <SparkWifiLine size={11} />,
  },
  memory: {
    label: "Memory",
    color: "purple",
    icon: <BrainCircuit size={11} />,
  },
  general: {
    label: "General",
    color: "default",
    icon: <Package size={11} />,
  },
};

export function PluginTypeTag({ type }: { type: PluginType }) {
  const { t } = useTranslation();
  const cfg = PLUGIN_TYPE_CONFIG[type] ?? PLUGIN_TYPE_CONFIG.general;
  return (
    <Tag
      color={cfg.color}
      icon={cfg.icon}
      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
    >
      {type === "memory" ? t("pluginManager.typeMemory", cfg.label) : cfg.label}
    </Tag>
  );
}
