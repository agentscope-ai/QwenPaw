import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Dropdown, Tag, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { Shield, Ban, AlertTriangle, CheckCircle } from "lucide-react";
import { DownOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

export type ToolExecutionLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

type SessionApprovalLevel = ToolExecutionLevel | null;

const LEVELS: readonly ToolExecutionLevel[] = [
  "STRICT",
  "SMART",
  "AUTO",
  "OFF",
];

const LEVEL_META: Record<
  ToolExecutionLevel,
  { color: string; icon: React.ReactNode }
> = {
  STRICT: { color: "#ff4d4f", icon: <Ban size={12} /> },
  SMART: { color: "#faad14", icon: <AlertTriangle size={12} /> },
  AUTO: { color: "#1890ff", icon: <Shield size={12} /> },
  OFF: { color: "#52c41a", icon: <CheckCircle size={12} /> },
};

function storageKey(chatId: string): string {
  return `approval_level-${chatId}`;
}

interface ApprovalLevelToggleProps {
  chatId: string | undefined;
  onChange?: (level: SessionApprovalLevel) => void;
}

const ApprovalLevelToggle: React.FC<ApprovalLevelToggleProps> = ({
  chatId,
  onChange,
}) => {
  const { t } = useTranslation();
  const [sessionLevel, setSessionLevel] = useState<SessionApprovalLevel>(null);

  useEffect(() => {
    if (!chatId) {
      setSessionLevel(null);
      return;
    }
    const saved = localStorage.getItem(storageKey(chatId));
    if (saved && LEVELS.includes(saved as ToolExecutionLevel)) {
      setSessionLevel(saved as ToolExecutionLevel);
    } else {
      setSessionLevel(null);
    }
  }, [chatId]);

  const handleSelect = useCallback(
    (level: SessionApprovalLevel) => {
      if (!chatId) return;
      setSessionLevel(level);
      if (level === null) {
        localStorage.removeItem(storageKey(chatId));
      } else {
        localStorage.setItem(storageKey(chatId), level);
      }
      onChange?.(level);
    },
    [chatId, onChange],
  );

  const isOverridden = sessionLevel !== null;
  const meta = isOverridden ? LEVEL_META[sessionLevel] : null;

  const menuItems: MenuProps["items"] = useMemo(() => {
    const items: MenuProps["items"] = [
      {
        key: "inherit",
        label: (
          <div>
            <div>
              {t("agentConfig.toolExecutionLevel.inherit", "Default Mode")}
            </div>
            <div style={{ fontSize: 12, color: "#999", marginTop: 2 }}>
              {t("agentConfig.toolExecutionLevel.inheritDesc", "")}
            </div>
          </div>
        ),
        icon: <Shield size={14} style={{ color: "#999", marginTop: 4 }} />,
        onClick: () => handleSelect(null),
      },
      { type: "divider" },
    ];

    for (const lv of LEVELS) {
      const m = LEVEL_META[lv];
      const name = t(`agentConfig.toolExecutionLevel.${lv.toLowerCase()}`, lv);
      const desc = t(
        `agentConfig.toolExecutionLevel.${lv.toLowerCase()}Desc`,
        "",
      );
      items.push({
        key: lv,
        label: (
          <div>
            <div>{name}</div>
            {desc && (
              <div style={{ fontSize: 12, color: "#999", marginTop: 2 }}>
                {desc}
              </div>
            )}
          </div>
        ),
        icon: React.cloneElement(m.icon as React.ReactElement, {
          style: { color: m.color, marginTop: desc ? 4 : 0 },
        }),
        onClick: () => handleSelect(lv),
      });
    }

    return items;
  }, [handleSelect, t]);

  return (
    <Tooltip title={t("agentConfig.toolExecutionLevelTitle")}>
      <Dropdown
        menu={{ items: menuItems, selectedKeys: [sessionLevel ?? "inherit"] }}
        trigger={["click"]}
      >
        <Tag
          style={{
            cursor: "pointer",
            userSelect: "none",
            borderColor: meta?.color,
            color: meta?.color,
            opacity: isOverridden ? 1 : 0.6,
            transition: "all 0.2s",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            lineHeight: "22px",
          }}
        >
          {meta?.icon ?? <Shield size={12} />}
          {isOverridden
            ? t(
                `agentConfig.toolExecutionLevel.${sessionLevel.toLowerCase()}`,
                sessionLevel,
              )
            : t("agentConfig.toolExecutionLevel.inherit", "Default Mode")}
          <DownOutlined style={{ fontSize: 10 }} />
        </Tag>
      </Dropdown>
    </Tooltip>
  );
};

export default ApprovalLevelToggle;
