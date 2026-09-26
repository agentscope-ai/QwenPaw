import { useId, useState } from "react";
import { Input, Segmented } from "antd";
import { Clock3, ChevronRight } from "lucide-react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";
import { useTranslation } from "react-i18next";
import { DurationWheel } from "./DurationWheel";
import { SharedModal } from "./SharedModal";
import { readSchedule, writeSchedule, scheduleDays } from "./scheduleValue";
import styles from "./SchedulePicker.module.less";

/** Edit common schedules directly; retain the original expression for advanced patterns. */
export function SchedulePicker({
  value = "0 9 * * *",
  onChange,
  disabled,
  id,
}: {
  value?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
  id?: string;
}) {
  const { t, i18n } = useTranslation();
  const surfaceId = useId();
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const parsed = readSchedule(value);
  const minutes = parsed?.minutes ?? 540;
  const days = parsed?.days ?? [];
  const mode =
    advanced || !parsed ? "custom" : days.length ? "weekly" : "daily";
  const weekday = new Intl.DateTimeFormat(
    i18n.resolvedLanguage || i18n.language,
    { weekday: "short", timeZone: "UTC" },
  );
  return (
    <LayoutGroup id={surfaceId}>
      <div
        id={id}
        className={styles.picker}
        data-disabled={disabled || undefined}
      >
        <Segmented
          value={mode}
          disabled={disabled}
          aria-label={t("cronJobs.repeatFrequency")}
          options={[
            { value: "daily", label: t("cronJobs.cronTypeDaily") },
            { value: "weekly", label: t("cronJobs.cronTypeWeekly") },
            { value: "custom", label: t("common.advancedSettings") },
          ]}
          onChange={(mode) => {
            setAdvanced(mode === "custom");
            if (mode !== "custom")
              onChange?.(
                writeSchedule(
                  minutes,
                  mode === "weekly" ? (days.length ? days : ["mon"]) : [],
                ),
              );
          }}
        />
        {mode === "custom" ? (
          <Input
            value={value}
            disabled={disabled}
            aria-label={t("cronJobs.cronExpression")}
            onChange={(event) => onChange?.(event.target.value)}
          />
        ) : (
          <>
            <motion.button
              type="button"
              className={styles.time}
              style={{ borderRadius: 14 }}
              layoutId={reduced ? undefined : surfaceId}
              disabled={disabled}
              aria-label={`${t("cronJobs.cronTime")}: ${String(
                Math.floor(minutes / 60),
              ).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`}
              onClick={() => setOpen(true)}
              whileTap={reduced ? undefined : { scale: 0.96 }}
            >
              <Clock3 size={19} />
              <span>
                <NumberFlow
                  value={Math.floor(minutes / 60)}
                  format={{ minimumIntegerDigits: 2 }}
                  respectMotionPreference
                />
                :
                <NumberFlow
                  value={minutes % 60}
                  format={{ minimumIntegerDigits: 2 }}
                  respectMotionPreference
                />
              </span>
              <ChevronRight size={16} />
            </motion.button>
            {mode === "weekly" && (
              <div
                className={styles.days}
                aria-label={t("cronJobs.repeatFrequency")}
              >
                {scheduleDays.map((day, index) => (
                  <button
                    type="button"
                    key={day}
                    disabled={disabled}
                    aria-pressed={days.includes(day)}
                    onClick={() => {
                      const next = days.includes(day)
                        ? days.filter((value) => value !== day)
                        : [...days, day];
                      if (next.length) onChange?.(writeSchedule(minutes, next));
                    }}
                  >
                    {weekday.format(new Date(Date.UTC(2024, 0, 1 + index)))}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
      <SharedModal
        open={open && !disabled}
        surfaceId={surfaceId}
        title={t("cronJobs.cronTime")}
        width={420}
        footer={null}
        onCancel={() => setOpen(false)}
      >
        <DurationWheel
          value={minutes}
          onChange={(next) => onChange?.(writeSchedule(next, days))}
        />
      </SharedModal>
    </LayoutGroup>
  );
}
