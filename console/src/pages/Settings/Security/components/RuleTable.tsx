import { useMemo, useState } from "react";
import { Button, Input, Switch, Tag, Empty } from "antd";
import { Eye, Pencil, Trash2, ChevronRight, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";
import { SharedModal } from "@/components/interaction/SharedModal";
import InlineHelp from "@/components/InlineHelp";
import type { MergedRule } from "../useToolGuard";
import styles from "./RuleTable.module.less";

interface RuleTableProps {
  rules: MergedRule[];
  enabled: boolean;
  onToggleRule: (ruleId: string, currentlyDisabled: boolean) => void;
  onToggleAutoDeny: (ruleId: string, currentlyAutoDeny: boolean) => void;
  onPreviewRule: (rule: MergedRule) => void;
  onEditRule: (rule: MergedRule) => void;
  onDeleteRule: (ruleId: string) => void;
}

export function RuleTable({
  rules,
  enabled,
  onToggleRule,
  onToggleAutoDeny,
  onPreviewRule,
  onEditRule,
  onDeleteRule,
}: RuleTableProps) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const [category, setCategory] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const grouped = useMemo(() => {
    const groups: Record<string, MergedRule[]> = {};
    for (const rule of rules)
      (groups[rule.category || "other"] ??= []).push(rule);
    return groups;
  }, [rules]);
  const label = (key: string) =>
    t(`security.rules.categories.${key}`, {
      defaultValue: key.replace(/_/g, " "),
    });
  const description = (rule: MergedRule) =>
    t(`security.rules.descriptions.${rule.id}`, {
      defaultValue: rule.description,
    });
  const selected = category
    ? (grouped[category] ?? []).filter((rule) =>
        `${rule.id} ${description(rule)}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      )
    : [];
  return (
    <LayoutGroup>
      <div className={styles.categories}>
        {Object.entries(grouped).map(([key, items]) => (
          <motion.button
            type="button"
            key={key}
            layoutId={reduced ? undefined : `rule-category:${key}`}
            className={styles.category}
            onClick={() => {
              setQuery("");
              setCategory(key);
            }}
            whileTap={reduced ? undefined : { scale: 0.98 }}
          >
            <span className={styles.categoryTop}>
              <strong>{label(key)}</strong>
              <ChevronRight size={17} />
            </span>
            <span className={styles.count}>
              <NumberFlow
                value={items.filter((rule) => !rule.disabled).length}
                respectMotionPreference
              />{" "}
              <small>/ {items.length}</small>
            </span>
            <span className={styles.meter} aria-hidden="true">
              <motion.span
                animate={{
                  width: `${
                    (items.filter((rule) => !rule.disabled).length /
                      items.length) *
                    100
                  }%`,
                }}
                transition={{ duration: reduced ? 0 : 0.25 }}
              />
            </span>
            <span className={styles.caption}>{t("common.enabled")}</span>
          </motion.button>
        ))}
      </div>
      <SharedModal
        open={category !== null}
        surfaceId={category ? `rule-category:${category}` : undefined}
        title={category ? label(category) : ""}
        onCancel={() => setCategory(null)}
        footer={null}
        width={840}
      >
        <Input
          prefix={<Search size={16} />}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("common.search")}
          aria-label={t("common.search")}
          allowClear
        />
        <div className={styles.rules}>
          {selected.map((rule) => (
            <article
              className={styles.rule}
              key={rule.id}
              data-disabled={rule.disabled || undefined}
            >
              <div className={styles.ruleHeading}>
                <div>
                  <code>{rule.id}</code>
                  <p>{description(rule)}</p>
                </div>
                <Switch
                  disabled={!enabled}
                  checked={!rule.disabled}
                  aria-label={`${t("security.enabled")}: ${rule.id}`}
                  onChange={() => onToggleRule(rule.id, rule.disabled)}
                />
              </div>
              <div className={styles.ruleFooter}>
                <Tag>{rule.severity}</Tag>
                <span>
                  {t(
                    `security.rules.${
                      rule.source === "builtin" ? "builtin" : "custom"
                    }`,
                  )}
                </span>
                <div className={styles.actions}>
                  <span>
                    {t("security.rules.autoDeny")}{" "}
                    <InlineHelp>
                      {t("security.rules.autoDenyTooltip")}
                    </InlineHelp>
                  </span>
                  <Switch
                    size="small"
                    disabled={!enabled || rule.disabled}
                    checked={rule.autoDeny}
                    aria-label={`${t("security.rules.autoDeny")}: ${rule.id}`}
                    onChange={() => onToggleAutoDeny(rule.id, rule.autoDeny)}
                  />
                  <Button
                    type="text"
                    aria-label={`${t("common.view")}: ${rule.id}`}
                    icon={<Eye size={16} />}
                    onClick={() => onPreviewRule(rule)}
                  />
                  {rule.source === "custom" && (
                    <>
                      <Button
                        type="text"
                        disabled={!enabled}
                        aria-label={`${t("security.rules.edit")}: ${rule.id}`}
                        icon={<Pencil size={16} />}
                        onClick={() => onEditRule(rule)}
                      />
                      <Button
                        type="text"
                        danger
                        disabled={!enabled}
                        aria-label={`${t("security.rules.delete")}: ${rule.id}`}
                        icon={<Trash2 size={16} />}
                        onClick={() => onDeleteRule(rule.id)}
                      />
                    </>
                  )}
                </div>
              </div>
            </article>
          ))}
          {!selected.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        </div>
      </SharedModal>
    </LayoutGroup>
  );
}
