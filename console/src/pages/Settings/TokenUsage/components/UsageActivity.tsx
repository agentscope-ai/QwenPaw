import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import dayjs, { type Dayjs } from "dayjs";
import { Tooltip } from "antd";
import { ChevronDown } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import { formatCompact } from "@/utils/formatNumber";
import type { TokenUsageRecord } from "@/api/types/tokenUsage";
import { buildActivity } from "../usageActivityData";
import styles from "./UsageActivity.module.less";

export function UsageActivity({
  records,
  startDate,
  endDate,
}: {
  records: TokenUsageRecord[];
  startDate: Dayjs;
  endDate: Dayjs;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const { days, models, max } = useMemo(
    () => buildActivity(records, startDate, endDate),
    [records, startDate, endDate],
  );
  const active = days.find((day) => day.date === selected && day.inRange);
  const total = models.reduce((sum, [, value]) => sum + value, 0);
  const activeDays = days.filter((day) => day.inRange && day.value > 0).length;
  const peak = days.reduce(
    (best, day) => (day.value > best.value ? day : best),
    days[0],
  );
  const elapsedDays = Math.max(
    1,
    Math.min(
      endDate.diff(startDate, "day") + 1,
      dayjs().startOf("day").diff(startDate.startOf("day"), "day") + 1,
    ),
  );
  const cellLabel = (day: (typeof days)[number]) =>
    `${day.date} · ${day.value.toLocaleString()} tokens`;
  return (
    <section
      className={styles.card}
      aria-label={t("tokenUsage.activity", "Activity")}
      style={{ "--weeks": days.length / 7 } as CSSProperties}
    >
      <header className={styles.header}>
        <div>
          <span>{t("tokenUsage.activity", "Activity")}</span>
          <h3>
            {formatCompact(total)} <small>tokens</small>
          </h3>
        </div>
        <span>
          {startDate.format("YYYY/MM/DD")} — {endDate.format("YYYY/MM/DD")}
        </span>
      </header>
      <div className={styles.activityBody}>
        <div className={styles.calendarLayout}>
          <div className={styles.weekdays} aria-hidden="true">
            {Array.from({ length: 7 }, (_, index) => (
              <span key={index}>
                {[0, 2, 4].includes(index)
                  ? dayjs("2024-01-01").add(index, "day").format("ddd")
                  : ""}
              </span>
            ))}
          </div>
          <div className={styles.scroll}>
            <div
              className={styles.calendar}
              style={{ "--weeks": days.length / 7 } as CSSProperties}
            >
              {days.map((day, index) => (
                <div key={day.date} className={styles.cellWrap}>
                  {index % 7 === 0 && (
                    <span className={styles.month}>
                      {index === 0
                        ? startDate.format("MMM")
                        : dayjs(day.date).month() !==
                          (index === 7
                            ? startDate
                            : dayjs(days[index - 7].date)
                          ).month()
                        ? dayjs(day.date).format("MMM")
                        : ""}
                    </span>
                  )}
                  {day.inRange ? (
                    <Tooltip title={cellLabel(day)}>
                      <button
                        type="button"
                        aria-label={
                          dayjs(day.date).isAfter(dayjs(), "day")
                            ? `${day.date} · ${t(
                                "tokenUsage.futureDate",
                                "Future date",
                              )}`
                            : cellLabel(day)
                        }
                        disabled={dayjs(day.date).isAfter(dayjs(), "day")}
                        data-future={dayjs(day.date).isAfter(dayjs(), "day")}
                        aria-pressed={selected === day.date}
                        className={styles.cell}
                        onClick={() => setSelected(day.date)}
                        style={
                          {
                            "--intensity": day.value
                              ? `${
                                  20 +
                                  (80 * Math.ceil((day.value / max) * 4)) / 4
                                }%`
                              : "0%",
                          } as CSSProperties
                        }
                      />
                    </Tooltip>
                  ) : (
                    <span className={styles.padding} />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className={styles.facts}>
          <div>
            <span>{t("tokenUsage.activeDays", "Active days")}</span>
            <strong>
              {activeDays}
              <small> / {elapsedDays}</small>
            </strong>
          </div>
          <div>
            <span>{t("tokenUsage.dailyAverage", "Daily average")}</span>
            <strong>
              {formatCompact(total / elapsedDays)}
              <small> tokens</small>
            </strong>
          </div>
          <div>
            <span>{t("tokenUsage.peakDay", "Peak day")}</span>
            <strong>
              {peak?.value ? dayjs(peak.date).format("MM/DD") : "—"}
              <small>
                {peak?.value ? ` · ${formatCompact(peak.value)}` : ""}
              </small>
            </strong>
          </div>
        </div>
      </div>
      <div className={styles.legend}>
        <span aria-live="polite">
          {active
            ? cellLabel(active)
            : t("tokenUsage.activityHint", "Select a day to inspect usage")}
        </span>
        <span>
          {t("tokenUsage.less", "Less")}{" "}
          {[0, 40, 60, 80, 100].map((value) => (
            <i
              key={value}
              style={{ "--intensity": `${value}%` } as CSSProperties}
            />
          ))}{" "}
          {t("tokenUsage.more", "More")}
        </span>
      </div>
      <button
        type="button"
        data-press
        className={styles.rankingToggle}
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        <span>{t("tokenUsage.modelRanking", "Model ranking")}</span>
        <span>
          {models.length}
          <ChevronDown
            size={16}
            style={{ transform: expanded ? "rotate(180deg)" : undefined }}
          />
        </span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: reduced ? "auto" : 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: reduced ? "auto" : 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 360, damping: 38 }}
            className={styles.ranking}
          >
            {models.length ? (
              models.map(([name, value]) => (
                <div key={name} className={styles.model}>
                  <span title={name}>{name}</span>
                  <strong>{formatCompact(value)}</strong>
                  <div>
                    <i
                      style={{ width: `${total ? (value / total) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              ))
            ) : (
              <p>{t("tokenUsage.noData")}</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
