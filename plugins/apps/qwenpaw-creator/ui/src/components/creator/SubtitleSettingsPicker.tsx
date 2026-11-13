import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, Select, Tooltip } from "antd";
import type { SelectProps } from "antd";

import type { SubtitleAnimationPolicy, SubtitleStyle } from "@/contracts/creator";
import SubtitleAnimationControls from "./SubtitleAnimationControls";
import SubtitleStyleControls from "./SubtitleStyleControls";
import SubtitleTemplatePicker from "./SubtitleTemplatePicker";

/**
 * The subtitle policy dropdown plus the style window that "auto" opens.
 *
 * The pill stays what it always was — the word 字幕 with a dot for state, and
 * 自动 / 关闭 in the dropdown — because that choice is worth two values and no
 * more room. What auto then draws (pack, colour, size, outline) is a browsing
 * task of six cards, so it gets a window: opening it on the pick is what the
 * dropdown used to promise without ever delivering, and picking 自动 again is
 * the way back in once the window has been closed.
 *
 * The window is sized against the viewport rather than to a fixed panel: the
 * composer is a narrow card on a laptop and a wide one on a monitor, so the
 * width is capped, the body scrolls on its own and the card strip takes up
 * whatever room is left.
 */

export type SubtitlePolicyChoice = "auto" | "off";

interface SubtitleSettingsPickerProps {
  policy: string;
  onPolicyChange: (value: SubtitlePolicyChoice) => void;
  template: string | null;
  onTemplateChange: (id: string | null) => void;
  style: SubtitleStyle | null;
  onStyleChange: (style: SubtitleStyle | null) => void;
  /**
   * Project-level entrance / exit / loop default.  The creation request
   * persists it, so captions drawn later keep the pick; leaving the host
   * without a change callback hides the picker (a pick that cannot land).
   */
  animation?: SubtitleAnimationPolicy | null;
  onAnimationChange?: (animation: SubtitleAnimationPolicy | null) => void;
  /** Same dropdown chrome as the resolution and ratio pills beside it. */
  selectClassNames?: SelectProps["classNames"];
}

export default function SubtitleSettingsPicker({
  policy,
  onPolicyChange,
  template,
  onTemplateChange,
  style,
  onStyleChange,
  animation = null,
  onAnimationChange,
  selectClassNames,
}: SubtitleSettingsPickerProps) {
  const { t } = useTranslation();
  const [styleOpen, setStyleOpen] = useState(false);
  // ``"on"`` is the legacy spelling of auto the launch state may still carry.
  const subtitleAuto = policy !== "off";
  const styleWindowOpen = styleOpen && subtitleAuto;
  const hints: Record<string, string> = {
    auto: t("home.subtitlePolicyAutoHint"),
    off: t("home.subtitlePolicyOffHint"),
  };

  return (
    <>
      <Tooltip title={t("home.subtitlePolicyTip")}>
        <Select
          aria-label={t("home.subtitlePolicy")}
          size="small"
          value={policy}
          onChange={(value) => onPolicyChange(value === "off" ? "off" : "auto")}
          onSelect={(value) => {
            if (value !== "off") setStyleOpen(true);
          }}
          options={[
            { value: "auto", label: t("home.subtitlePolicyAuto") },
            { value: "off", label: t("home.subtitlePolicyOff") },
          ]}
          labelRender={() => (
            <span className="inline-flex items-center justify-center gap-1">
              {/* The pill always reads "字幕" and keeps the neutral look of its
                  neighbours; only the leading dot carries the state. */}
              <span
                aria-hidden
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  subtitleAuto
                    ? "bg-[var(--color-success)]"
                    : "bg-[var(--color-text-tertiary)]"
                }`}
              />
              {t("home.subtitlePolicy")}
            </span>
          )}
          optionRender={(option) => (
            <span className="flex flex-col gap-0.5 py-0.5 text-left">
              <span className="!text-xs !font-semibold !text-[var(--color-text-primary)]">
                {option.data.label}
              </span>
              <span className="!text-[11px] !font-normal !text-[var(--color-text-tertiary)]">
                {hints[String(option.data.value ?? "")]}
              </span>
            </span>
          )}
          popupMatchSelectWidth={false}
          variant="borderless"
          className="!h-8 !w-auto min-w-[80px] !rounded-full !bg-[rgba(43,27,0,0.04)] dark:!bg-white/5"
          classNames={selectClassNames}
        />
      </Tooltip>

      {/* The dropdown underneath can revoke the policy while this is open, so
          it closes without the fade: an animated Modal keeps its content
          mounted and clickable through the whole leave. */}
      <Modal
        open={styleWindowOpen}
        onCancel={() => setStyleOpen(false)}
        title={t("home.subtitleTemplateLabel")}
        footer={null}
        centered
        transitionName=""
        maskTransitionName=""
        width={860}
        style={{ maxWidth: "calc(100vw - 32px)" }}
        styles={{
          body: {
            maxHeight: "min(70vh, 560px)",
            overflowY: "auto",
            overscrollBehavior: "contain",
          },
        }}
      >
        <div data-subtitle-style-modal className="pt-1">
          <p className="mb-3 text-xs leading-5 text-[var(--color-text-secondary)]">
            {t("home.subtitleStyleWinDesc")}
          </p>

          <SubtitleTemplatePicker
            value={template}
            onChange={onTemplateChange}
            style={style}
            animation={animation}
            onSelectCustom={(custom) => {
              onTemplateChange(custom.packId ?? null);
              onStyleChange(custom.style ?? null);
              onAnimationChange?.(custom.animation ?? null);
            }}
          />

          <div className="mt-4 border-t border-[var(--color-border)] pt-3">
            <SubtitleStyleControls value={style} onChange={onStyleChange} />
          </div>

          {onAnimationChange && (
            <div className="mt-4 border-t border-[var(--color-border)] pt-3">
              <SubtitleAnimationControls
                value={animation}
                onChange={onAnimationChange}
                allowClear
              />
            </div>
          )}

          <div className="mt-4 flex justify-end">
            <Button
              type="primary"
              size="small"
              onClick={() => setStyleOpen(false)}
            >
              {t("common.done")}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
