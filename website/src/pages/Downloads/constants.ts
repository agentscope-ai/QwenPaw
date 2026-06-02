import { Laptop, Monitor, type LucideIcon } from "lucide-react";

export const CDN_BASE = "https://download.qwenpaw.agentscope.io";

export const DOWNLOADS_HEADER_BG_URL =
  "https://img.alicdn.com/imgextra/i2/O1CN01DAtS4T1FJTi3kRSot_!!6000000000466-2-tps-2880-554.png";

export const PLATFORM_ICONS: Record<string, LucideIcon> = {
  win: Monitor,
  mac: Laptop,
  linux: Monitor,
};

export const KNOWN_PLUGIN_PLATFORM_KINDS = ["bundle", "tool"] as const;
