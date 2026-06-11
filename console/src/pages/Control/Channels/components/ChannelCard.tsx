import { useTranslation } from "react-i18next";
import React from "react";
import { ChannelIcon } from "./ChannelIcon";
import { getChannelLabel, type ChannelKey } from "./constants";

interface ChannelCardProps {
  channelKey: ChannelKey;
  config: Record<string, unknown>;
  onClick: () => void;
}

export const ChannelCard = React.memo(function ChannelCard({
  channelKey,
  config,
  onClick,
}: ChannelCardProps) {
  const { t } = useTranslation();
  const enabled = Boolean(config.enabled);
  const isBuiltin = Boolean(config.isBuiltin);
  const label = getChannelLabel(channelKey, t);
  const botPrefix =
    typeof config.bot_prefix === "string" ? config.bot_prefix : "";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      className={`
        group border rounded-xl p-6 cursor-pointer transition-all select-none
        hover:border-primary/60 hover:shadow-md
        ${
          enabled
            ? "border-green-500/40 bg-green-500/5"
            : "border-border bg-card"
        }
      `}
    >
      {/* Top: Icon + Status */}
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-muted">
          <ChannelIcon channelKey={channelKey} size={28} />
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              enabled ? "bg-green-500" : "bg-muted-foreground/40"
            }`}
          />
          <span
            className={`text-xs ${
              enabled
                ? "text-green-600 dark-mode:text-green-400"
                : "text-muted-foreground"
            }`}
          >
            {enabled ? t("common.enabled") : t("common.disabled")}
          </span>
        </div>
      </div>

      {/* Middle: Name + Tag */}
      <div className="flex items-center gap-2 mb-2">
        <span className="font-semibold text-sm">{label}</span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
            isBuiltin
              ? "bg-primary/10 text-primary"
              : "bg-secondary text-secondary-foreground"
          }`}
        >
          {isBuiltin ? t("channels.builtin") : t("channels.custom")}
        </span>
      </div>

      {/* Bottom: Bot Prefix */}
      <div className="text-xs text-muted-foreground">
        {t("channels.botPrefix")}: {botPrefix || t("channels.notSet")}
      </div>
    </div>
  );
});
