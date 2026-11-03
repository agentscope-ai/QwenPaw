import { useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Input } from "antd";
import { useTranslation } from "react-i18next";
import { ModelPickerPopover } from "../../Chat/ModelSelector/ModelPickerPopover";
import styles from "./DefaultModelPicker.module.less";

export function DefaultModelPicker({
  id,
  value,
  onChange,
  options,
}: {
  id?: string;
  value?: string;
  onChange?: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const setVisible = (next: boolean) => {
    setOpen(next);
    if (!next) setQuery("");
  };
  const filtered = options.filter((option) =>
    option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  return (
    <ModelPickerPopover
      open={open}
      onOpenChange={setVisible}
      content={
        <div className={styles.panel}>
          <Input
            autoFocus
            prefix={<Search size={15} />}
            value={query}
            aria-label={t("modelSelector.searchModels")}
            placeholder={t("modelSelector.searchModels")}
            onChange={(event) => setQuery(event.target.value)}
            allowClear
          />
          <div className={styles.options}>
            {filtered.map((option) => (
              <button
                type="button"
                key={option.value}
                aria-pressed={option.value === value}
                onClick={() => {
                  onChange?.(option.value);
                  setVisible(false);
                }}
              >
                <span>{option.label}</span>
                {option.value === value && <Check size={16} />}
              </button>
            ))}
            {!filtered.length && <p>{t("modelSelector.noModelsFound")}</p>}
          </div>
        </div>
      }
    >
      <button
        id={id}
        aria-label={t("hub.governance.models.defaultModel")}
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <span>
          {options.find((option) => option.value === value)?.label ??
            t("hub.governance.models.chooseDefault")}
        </span>
        <ChevronDown size={15} />
      </button>
    </ModelPickerPopover>
  );
}
