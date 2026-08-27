import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { Check, ChevronDown, ShieldCheck, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { HarnessApprovalPreset } from "@/api/modules/harness";
import { useIsMobile } from "../../../hooks/useIsMobile";
import { OsDrawer } from "../../../os/OsOverlay";
import drawerStyles from "./ApprovalToggle.module.less";
import styles from "./HarnessApprovalToggle.module.less";

interface HarnessApprovalToggleProps {
  backend: string;
  sessionId: string;
  presets: HarnessApprovalPreset[];
  onChange: (settings: Record<string, unknown>) => void;
  className?: string;
  compact?: boolean;
}

function storageKey(backend: string, sessionId: string): string {
  return `harness-approval-${backend}-${sessionId}`;
}

export default function HarnessApprovalToggle({
  backend,
  sessionId,
  presets,
  onChange,
  className,
  compact = false,
}: HarnessApprovalToggleProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const defaultPreset = presets[0];
  const [selectedId, setSelectedId] = useState(defaultPreset?.id ?? "");
  const [open, setOpen] = useState(false);
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
  const selectPreset = useCallback(
    (preset: HarnessApprovalPreset) => {
      setSelectedId(preset.id);
      setOpen(false);
      localStorage.setItem(storageKey(backend, sessionId), preset.id);
      onChangeRef.current(preset.settings);
    },
    [backend, sessionId],
  );
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
        onClick: () => selectPreset(preset),
      })),
    [presets, selectPreset, t],
  );

  if (!selected) return null;
  const trigger = (
    <button
      className={[styles.trigger, className].filter(Boolean).join(" ")}
      aria-expanded={open}
      aria-haspopup="listbox"
      aria-label={t("agent.backend.approvalMode")}
      onClick={isMobile ? () => setOpen((current) => !current) : undefined}
      type="button"
    >
      <ShieldCheck size={13} />
      {!compact && (
        <>
          {t(
            `agent.backend.approvalPresets.${selected.id}.name`,
            selected.name,
          )}
          <ChevronDown size={12} />
        </>
      )}
    </button>
  );

  if (isMobile) {
    return (
      <>
        {trigger}
        <OsDrawer
          aria-label={t("agent.backend.approvalMode")}
          open={open}
          placement="bottom"
          height="auto"
          closable={false}
          destroyOnHidden
          onClose={() => setOpen(false)}
          styles={{
            body: { padding: 0, overflow: "hidden" },
            content: {
              borderRadius: "14px 14px 0 0",
              overflow: "hidden",
            },
            wrapper: { maxHeight: "min(52dvh, 430px)" },
          }}
        >
          <div className={drawerStyles.sheet}>
            <div className={drawerStyles.sheetHeader}>
              <strong>{t("agent.backend.approvalMode")}</strong>
              <button
                type="button"
                aria-label={t("common.close")}
                className={drawerStyles.closeButton}
                onClick={() => setOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <div className={drawerStyles.optionList} role="listbox">
              {presets.map((preset) => {
                const presetSelected = preset.id === selected.id;
                return (
                  <button
                    type="button"
                    role="option"
                    aria-selected={presetSelected}
                    className={`${drawerStyles.option} ${
                      presetSelected ? drawerStyles.optionSelected : ""
                    }`}
                    data-preset-id={preset.id}
                    key={preset.id}
                    onClick={() => selectPreset(preset)}
                  >
                    <span className={drawerStyles.optionIcon}>
                      <ShieldCheck size={15} />
                    </span>
                    <span className={drawerStyles.optionCopy}>
                      <strong>
                        {t(
                          `agent.backend.approvalPresets.${preset.id}.name`,
                          preset.name,
                        )}
                      </strong>
                      <small>
                        {t(
                          `agent.backend.approvalPresets.${preset.id}.description`,
                          preset.description,
                        )}
                      </small>
                    </span>
                    {presetSelected && <Check size={16} />}
                  </button>
                );
              })}
            </div>
          </div>
        </OsDrawer>
      </>
    );
  }

  return (
    <Tooltip title={t("agent.backend.approvalMode")}>
      <Dropdown
        menu={{ items, selectedKeys: [selected.id] }}
        trigger={["click"]}
        open={open}
        onOpenChange={setOpen}
      >
        {trigger}
      </Dropdown>
    </Tooltip>
  );
}
