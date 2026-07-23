import { useEffect, useMemo, useRef, useState } from "react";
import { Dropdown, Tag, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { ChevronDown, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { HarnessApprovalPreset } from "@/api/modules/harness";
import styles from "./HarnessApprovalToggle.module.less";

interface HarnessApprovalToggleProps {
  backend: string;
  sessionId: string;
  presets: HarnessApprovalPreset[];
  onChange: (settings: Record<string, unknown>) => void;
}

function storageKey(backend: string, sessionId: string): string {
  return `harness-approval-${backend}-${sessionId}`;
}

export default function HarnessApprovalToggle({
  backend,
  sessionId,
  presets,
  onChange,
}: HarnessApprovalToggleProps) {
  const { t } = useTranslation();
  const defaultPreset = presets[0];
  const [selectedId, setSelectedId] = useState(defaultPreset?.id ?? "");
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const saved = localStorage.getItem(storageKey(backend, sessionId));
    const selected = presets.find((item) => item.id === saved) ?? presets[0];
    setSelectedId(selected?.id ?? "");
    onChangeRef.current(selected?.settings ?? {});
  }, [backend, presets, sessionId]);

  const selected =
    presets.find((item) => item.id === selectedId) ?? defaultPreset;
  const items: MenuProps["items"] = useMemo(
    () =>
      presets.map((preset) => ({
        key: preset.id,
        label: (
          <div>
            <div>
              {t(
                `agent.backend.approvalPresets.${preset.id}.name`,
                preset.name,
              )}
            </div>
            <div className={styles.description}>
              {t(
                `agent.backend.approvalPresets.${preset.id}.description`,
                preset.description,
              )}
            </div>
          </div>
        ),
        onClick: () => {
          setSelectedId(preset.id);
          localStorage.setItem(storageKey(backend, sessionId), preset.id);
          onChangeRef.current(preset.settings);
        },
      })),
    [backend, presets, sessionId, t],
  );

  if (!selected) return null;
  return (
    <Tooltip title={t("agent.backend.approvalMode")}>
      <Dropdown
        menu={{ items, selectedKeys: [selected.id] }}
        trigger={["click"]}
      >
        <Tag color="orange" className={styles.trigger}>
          <ShieldCheck size={13} />
          {t(
            `agent.backend.approvalPresets.${selected.id}.name`,
            selected.name,
          )}
          <ChevronDown size={12} />
        </Tag>
      </Dropdown>
    </Tooltip>
  );
}
