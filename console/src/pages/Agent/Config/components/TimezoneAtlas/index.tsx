import { lazy, Suspense, useEffect, useId, useMemo, useState } from "react";
import { Button, Select, Spin } from "antd";
import { Globe2, LocateFixed, ArrowUpRight } from "lucide-react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { getTimeZones } from "@vvo/tzdb";
import NumberFlow from "@number-flow/react";
import { useTranslation } from "react-i18next";
import { SharedModal } from "@/components/interaction/SharedModal";
import styles from "./index.module.less";
import {
  fixedTimezone,
  timezoneOffset,
  offsetLabel,
  timezoneName,
} from "./timezones";

const WorldMap = lazy(() => import("./WorldMap"));
const zones = getTimeZones({ includeUtc: true });

export default function TimezoneAtlas({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const [zoneOpen, setZoneOpen] = useState(false);
  const selectZone = (zone: string) => {
    setZoneOpen(false);
    onChange(zone);
  };
  const [now, setNow] = useState(() => new Date());
  const reduced = useReducedMotion();
  const id = useId();
  const language = i18n.resolvedLanguage || i18n.language;
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const zone = zones.find(
    (zone) => zone.name === value || zone.group.includes(value),
  );
  const selectedZone = zone?.name ?? value ?? "UTC";
  const currentOffset = timezoneOffset(selectedZone, now);
  const timezoneLabel = timezoneName(
    selectedZone,
    language,
    t("runtimeDesign.beijingTime"),
    now,
  );
  const options = useMemo(() => {
    const describe = (name: string) =>
      timezoneName(name, language, t("runtimeDesign.beijingTime"), now);
    const fixed = Array.from({ length: 27 }, (_, index) => {
      const minutes = (index - 12) * 60;
      return {
        value: fixedTimezone(minutes),
        label: offsetLabel(minutes),
        offset: minutes,
        search: offsetLabel(minutes),
      };
    });
    const regional = zones
      .filter((zone) => zone.name !== "UTC")
      .map((zone) => {
        const offset = timezoneOffset(zone.name, now);
        const label = `${offsetLabel(offset)} · ${describe(zone.name)}`;
        return {
          value: zone.name,
          label,
          offset,
          search: `${label} ${zone.name} ${zone.group.join(" ")}`,
        };
      });
    // Identically named regional time zones retain their IANA identifier for disambiguation.
    const counts = new Map<string, number>();
    regional.forEach((option) =>
      counts.set(option.label, (counts.get(option.label) || 0) + 1),
    );
    return [
      ...fixed,
      ...regional.map((option) => ({
        ...option,
        label:
          counts.get(option.label)! > 1
            ? `${option.label} · ${option.value}`
            : option.label,
      })),
    ].sort((a, b) => a.offset - b.offset);
  }, [language, now, t]);
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat(language, {
      timeZone: selectedZone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZoneName: "shortOffset",
    }).formatToParts(now);
  } catch {
    parts = new Intl.DateTimeFormat(language, {
      timeZone: "UTC",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZoneName: "shortOffset",
    }).formatToParts(now);
  }
  const hours = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minutes = Number(
    parts.find((part) => part.type === "minute")?.value ?? 0,
  );
  const offset = offsetLabel(currentOffset);
  const clock = (
    <span className={styles.clock}>
      <NumberFlow
        value={hours}
        format={{ minimumIntegerDigits: 2 }}
        respectMotionPreference
      />
      <span>:</span>
      <NumberFlow
        value={minutes}
        format={{ minimumIntegerDigits: 2 }}
        respectMotionPreference
      />
    </span>
  );
  return (
    <LayoutGroup id={id}>
      <motion.button
        type="button"
        className={styles.trigger}
        style={{ borderRadius: 18 }}
        layoutId={reduced ? undefined : id}
        onClick={() => setOpen(true)}
        disabled={disabled}
        aria-label={`${t("agentConfig.timezone")}: ${value}`}
      >
        <Globe2 size={22} />
        <span className={styles.place}>
          <strong>{timezoneLabel}</strong>
          <small>{offset}</small>
        </span>
        {clock}
        <ArrowUpRight size={18} />
      </motion.button>
      <SharedModal
        open={open}
        surfaceId={id}
        onCancel={() => setOpen(false)}
        footer={null}
        width={860}
        title={t("agentConfig.timezone")}
      >
        <div className={styles.atlas}>
          <div className={styles.toolbar}>
            <Select
              showSearch
              value={selectedZone}
              disabled={disabled}
              onChange={selectZone}
              open={zoneOpen}
              onDropdownVisibleChange={setZoneOpen}
              options={options}
              aria-label={t("agentConfig.selectTimezone")}
              filterOption={(input, option) =>
                `${option?.label} ${option?.search}`
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
            />
            <Button
              icon={<LocateFixed size={16} />}
              disabled={disabled}
              onClick={() =>
                selectZone(Intl.DateTimeFormat().resolvedOptions().timeZone)
              }
            >
              {t("runtimeDesign.deviceTimezone")}
            </Button>
          </div>
          <div className={styles.readout}>
            <div>
              <span>{t("runtimeDesign.localTime")}</span>
              <h3>{timezoneLabel}</h3>
              <small>{offset}</small>
            </div>
            {clock}
          </div>
          <Suspense
            fallback={
              <div className={styles.map}>
                <Spin />
              </div>
            }
          >
            <WorldMap
              value={selectedZone}
              offset={currentOffset}
              onOffsetChange={(minutes) => selectZone(fixedTimezone(minutes))}
              label={() => offset}
              disabled={disabled}
            />
          </Suspense>
          <p className={styles.hint}>{t("runtimeDesign.mapHint")}</p>
        </div>
      </SharedModal>
    </LayoutGroup>
  );
}
