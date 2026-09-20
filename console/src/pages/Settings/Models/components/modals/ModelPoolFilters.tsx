import { Input, Button } from "@agentscope-ai/design";
import { Select } from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  emptyPoolFilters,
  type ModelPoolFilters as Filters,
} from "./modelPool";
import styles from "./ModelPool.module.less";

export function ModelPoolFilters({
  value,
  onChange,
  families,
}: {
  value: Filters;
  onChange: (filters: Filters) => void;
  families: string[];
}) {
  const { t } = useTranslation();
  const filter = (key: keyof Filters, choices: string[], prefix: string) => (
    <Select
      aria-label={t(`models.pool.${key}`)}
      value={value[key]}
      onChange={(next) => onChange({ ...value, [key]: next })}
      options={choices.map((item) => ({
        value: item,
        label:
          item === "all" ? t(`models.pool.${key}`) : t(`${prefix}.${item}`),
      }))}
      popupMatchSelectWidth={false}
    />
  );
  return (
    <div className={styles.filters}>
      <Input
        aria-label={t("models.searchModelPlaceholder")}
        prefix={<Search size={18} />}
        placeholder={t("models.searchModelPlaceholder")}
        value={value.search}
        allowClear
        onChange={(event) => onChange({ ...value, search: event.target.value })}
      />
      <div className={styles.filterRow}>
        {filter(
          "billing",
          ["all", "free", "paid", "unknown"],
          "models.billing",
        )}
        {filter(
          "capability",
          ["all", "image", "audio", "video", "tool_calling", "unknown"],
          "models.pool.capabilityOptions",
        )}
        {filter(
          "availability",
          [
            "all",
            "available",
            "unverified",
            "permission_denied",
            "model_not_found",
            "rate_limited",
            "transient_error",
            "incompatible_api",
          ],
          "models.pool.status",
        )}
        {families.length > 1 && (
          <Select
            aria-label={t("models.pool.family")}
            value={value.family}
            onChange={(family) => onChange({ ...value, family })}
            options={[
              { value: "all", label: t("models.pool.family") },
              ...families.map((family) => ({ value: family, label: family })),
            ]}
          />
        )}
        {Object.keys(value).some(
          (key) =>
            value[key as keyof Filters] !==
            emptyPoolFilters[key as keyof Filters],
        ) && (
          <Button type="text" onClick={() => onChange(emptyPoolFilters)}>
            {t("models.pool.clear")}
          </Button>
        )}
      </div>
    </div>
  );
}
