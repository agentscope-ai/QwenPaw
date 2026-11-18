import type { ReactNode } from "react";
import { Input, Button } from "@agentscope-ai/design";
import { Popover, Select, Tag, Tooltip } from "antd";
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
  actions,
}: {
  value: Filters;
  onChange: (filters: Filters) => void;
  families: string[];
  actions?: ReactNode;
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
      <div className={styles.searchTools}>
        <Input
          aria-label={t("models.searchModelPlaceholder")}
          prefix={<Search size={18} />}
          placeholder={t("models.searchModelPlaceholder")}
          value={value.search}
          allowClear
          onChange={(event) =>
            onChange({ ...value, search: event.target.value })
          }
        />
        {actions}
      </div>
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
          <Tooltip title={t("models.billing.free")}>
            <Gift size={16} aria-label={t("models.billing.free")} />
          </Tooltip>
        </button>
        <button
          type="button"
          className={styles.filterChip}
          aria-pressed={value.multimodal}
          onClick={() => onChange({ ...value, multimodal: !value.multimodal })}
        >
          <Tooltip title={t("models.tagMultimodal")}>
            <Boxes size={16} aria-label={t("models.tagMultimodal")} />
          </Tooltip>
        </button>
        <button
          type="button"
          className={styles.filterChip}
          aria-pressed={value.tools}
          onClick={() => onChange({ ...value, tools: !value.tools })}
        >
          <Tooltip title={t("models.pool.capabilityOptions.tool_calling")}>
            <Wrench
              size={16}
              aria-label={t("models.pool.capabilityOptions.tool_calling")}
            />
          </Tooltip>
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
          <Button
            type="text"
            title={t("models.pool.moreFilters")}
            aria-label={t("models.pool.moreFilters")}
            icon={<SlidersHorizontal size={17} />}
          />
        </Popover>
      </div>
      <div
        className={styles.activeFilters}
        style={{ display: active.length || value.search ? undefined : "none" }}
      >
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
