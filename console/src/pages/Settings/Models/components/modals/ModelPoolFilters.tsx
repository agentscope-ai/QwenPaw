import { Input, Button } from "@agentscope-ai/design";
import { Popover, Select, Tag } from "antd";
import { Boxes, Gift, Search, SlidersHorizontal, Wrench } from "lucide-react";
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
  const labels: Record<string, string> = {
    billing:
      value.billing === "all" ? "" : t(`models.billing.${value.billing}`),
    capability:
      value.capability === "all"
        ? ""
        : t(`models.pool.capabilityOptions.${value.capability}`),
    availability:
      value.availability === "all"
        ? ""
        : t(`models.pool.status.${value.availability}`),
    family: value.family === "all" ? "" : value.family,
    multimodal: value.multimodal ? t("models.tagMultimodal") : "",
    tools: value.tools ? t("models.pool.capabilityOptions.tool_calling") : "",
  };
  const active = Object.entries(labels).filter(([, label]) => Boolean(label));
  const group = (
    key: "billing" | "capability" | "availability",
    choices: string[],
    prefix: string,
  ) => (
    <fieldset className={styles.filterGroup}>
      <legend>{t(`models.pool.filterLabels.${key}`)}</legend>
      <div>
        {choices.map((item) => (
          <button
            type="button"
            key={item}
            aria-pressed={value[key] === item}
            className={styles.filterChip}
            onClick={() => onChange({ ...value, [key]: item })}
          >
            {t(item === "all" ? "models.pool.any" : `${prefix}.${item}`)}
          </button>
        ))}
      </div>
    </fieldset>
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
      <div className={styles.quickFilters}>
        <button
          type="button"
          className={styles.filterChip}
          aria-pressed={value.billing === "free"}
          onClick={() =>
            onChange({
              ...value,
              billing: value.billing === "free" ? "all" : "free",
            })
          }
        >
          <Gift size={14} />
          {t("models.billing.free")}
        </button>
        <button
          type="button"
          className={styles.filterChip}
          aria-pressed={value.multimodal}
          onClick={() => onChange({ ...value, multimodal: !value.multimodal })}
        >
          <Boxes size={14} />
          {t("models.tagMultimodal")}
        </button>
        <button
          type="button"
          className={styles.filterChip}
          aria-pressed={value.tools}
          onClick={() => onChange({ ...value, tools: !value.tools })}
        >
          <Wrench size={14} />
          {t("models.pool.capabilityOptions.tool_calling")}
        </button>
        <Popover
          trigger="click"
          placement="bottomRight"
          content={
            <div className={styles.moreFilters}>
              {group(
                "billing",
                ["all", "free", "paid", "unknown"],
                "models.billing",
              )}
              {group(
                "capability",
                ["all", "image", "audio", "video", "tool_calling", "unknown"],
                "models.pool.capabilityOptions",
              )}
              {group(
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
                <fieldset className={styles.filterGroup}>
                  <legend>{t("models.pool.filterLabels.family")}</legend>
                  <Select
                    aria-label={t("models.pool.family")}
                    value={value.family}
                    showSearch
                    optionFilterProp="label"
                    onChange={(family) => onChange({ ...value, family })}
                    options={[
                      { value: "all", label: t("models.pool.any") },
                      ...families.map((family) => ({
                        value: family,
                        label: family,
                      })),
                    ]}
                  />
                </fieldset>
              )}
            </div>
          }
        >
          <Button type="text" icon={<SlidersHorizontal size={15} />}>
            {t("models.pool.moreFilters")}
          </Button>
        </Popover>
      </div>
      <div className={styles.activeFilters}>
        {active.map(([key, label]) => (
          <Tag
            key={key}
            closable
            onClose={() =>
              onChange({
                ...value,
                [key]: emptyPoolFilters[key as keyof Filters],
              })
            }
          >
            {label}
          </Tag>
        ))}
        {(active.length > 0 || value.search) && (
          <Button
            size="small"
            type="text"
            onClick={() => onChange({ ...emptyPoolFilters })}
          >
            {t("models.pool.clear")}
          </Button>
        )}
      </div>
    </div>
  );
}
