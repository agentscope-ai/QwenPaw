import { ModelPickerPopover } from "./ModelPickerPopover";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { lazy, Suspense, useState } from "react";
import { Spin } from "antd";
import { ChevronRight } from "lucide-react";
import type { ModelSlotConfig } from "@/api/types";
import styles from "./index.module.less";
const ModelSelector = lazy(() => import("./index"));
export function ModelChoice({
  value,
  ariaLabel,
  label,
  onChange,
  disabled,
  open: controlledOpen,
  onOpenChange,
}: {
  ariaLabel?: string;
  value?: ModelSlotConfig | null;
  label: string;
  onChange: (value: ModelSlotConfig) => void;
  disabled?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = (next: boolean) => {
    setLocalOpen(next);
    onOpenChange?.(next);
  };
  return (
    <ModelPickerPopover
      open={open}
      onOpenChange={(next) => !disabled && setOpen(next)}
      content={
        <>
          {open && (
            <Suspense fallback={<Spin />}>
              <ModelSelector
                embedded
                selectedSlot={value}
                onPick={(provider_id, model) => {
                  onChange({ provider_id, model });
                  setOpen(false);
                }}
              />
            </Suspense>
          )}
        </>
      }
    >
      <button
        aria-label={ariaLabel}
        type="button"
        className={styles.modelChoiceButton}
        disabled={disabled}
        aria-expanded={open}
      >
        {value && <ProviderIcon providerId={value.provider_id} size={16} />}
        <span>{label}</span>
        <ChevronRight size={15} />
      </button>
    </ModelPickerPopover>
  );
}
