import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { useTranslation } from "react-i18next";
import type { ToolGuardRulesIntegrity } from "../api/client";
import styles from "./RuleIntegrityRepairBanner.module.less";

const MIN_RED_DISPLAY_MS = 5000;
const DEFAULT_TIMEOUT_MAX = 5;

interface RuleIntegrityRepairBannerProps {
  rulesIntegrity: ToolGuardRulesIntegrity | null;
  layout?: "inline" | "global";
}

type BannerPhase = "none" | "red" | "green";

function isRedIntegrityState(rulesIntegrity: ToolGuardRulesIntegrity): boolean {
  return (
    !rulesIntegrity.ok ||
    !!rulesIntegrity.rules_disabled ||
    !!rulesIntegrity.auto_repair_in_progress ||
    !!rulesIntegrity.auto_repair_abandoned
  );
}

function isGreenIntegrityState(rulesIntegrity: ToolGuardRulesIntegrity): boolean {
  return !!rulesIntegrity.auto_repair_completed && rulesIntegrity.ok;
}

function isTamperBannerCycleActive(
  rulesIntegrity: ToolGuardRulesIntegrity,
): boolean {
  return !!rulesIntegrity.tamper_banner_cycle_active;
}

function ensureRedStarted(redStartedAtRef: MutableRefObject<number | null>) {
  if (redStartedAtRef.current === null) {
    redStartedAtRef.current = Date.now();
  }
}

function scheduleGreenTransition(
  redStartedAtRef: MutableRefObject<number | null>,
  greenTimerRef: MutableRefObject<number | null>,
  setBannerPhase: (phase: BannerPhase) => void,
) {
  const redStartedAt = redStartedAtRef.current;
  if (redStartedAt === null) {
    setBannerPhase("green");
    return;
  }

  const remaining = MIN_RED_DISPLAY_MS - (Date.now() - redStartedAt);
  if (remaining <= 0) {
    setBannerPhase("green");
    redStartedAtRef.current = null;
    return;
  }

  setBannerPhase("red");
  greenTimerRef.current = window.setTimeout(() => {
    greenTimerRef.current = null;
    redStartedAtRef.current = null;
    setBannerPhase("green");
  }, remaining);
}

function resolveRedBannerTitle(
  rulesIntegrity: ToolGuardRulesIntegrity,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const timeoutMax =
    rulesIntegrity.auto_repair_timeout_max ?? DEFAULT_TIMEOUT_MAX;

  if (rulesIntegrity.auto_repair_abandoned) {
    return t("security.rulesIntegrity.autoRepairTimeoutAbandonedTitle", {
      max: timeoutMax,
      defaultValue:
        "连接超时，自动修复已放弃（已连续{{max}}次失败）",
    });
  }

  const timeoutRetry = rulesIntegrity.auto_repair_timeout_retry ?? 0;
  if (timeoutRetry > 0) {
    return t("security.rulesIntegrity.autoRepairTimeoutRetryTitle", {
      current: timeoutRetry,
      max: timeoutMax,
      defaultValue: "连接超时，正在重试修复第{{current}}/{{max}}次",
    });
  }

  return t("security.rulesIntegrity.tamperedAutoRepairTitle", {
    defaultValue: "安全配置文件被篡改，所有规则已被禁用，正在修复中",
  });
}

export function RuleIntegrityRepairBanner({
  rulesIntegrity,
  layout = "inline",
}: RuleIntegrityRepairBannerProps) {
  const { t } = useTranslation();
  const [bannerPhase, setBannerPhase] = useState<BannerPhase>("none");
  const redStartedAtRef = useRef<number | null>(null);
  const greenTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (greenTimerRef.current !== null) {
      window.clearTimeout(greenTimerRef.current);
      greenTimerRef.current = null;
    }

    if (!rulesIntegrity) {
      setBannerPhase("none");
      redStartedAtRef.current = null;
      return;
    }

    const cycleActive = isTamperBannerCycleActive(rulesIntegrity);

    if (isRedIntegrityState(rulesIntegrity)) {
      ensureRedStarted(redStartedAtRef);
      setBannerPhase("red");
      return;
    }

    if (isGreenIntegrityState(rulesIntegrity)) {
      if (cycleActive) {
        ensureRedStarted(redStartedAtRef);
        scheduleGreenTransition(
          redStartedAtRef,
          greenTimerRef,
          setBannerPhase,
        );
        return;
      }

      setBannerPhase("green");
      return;
    }

    if (!cycleActive) {
      setBannerPhase("none");
      redStartedAtRef.current = null;
      return;
    }

    ensureRedStarted(redStartedAtRef);
    setBannerPhase("red");
  }, [rulesIntegrity]);

  useEffect(
    () => () => {
      if (greenTimerRef.current !== null) {
        window.clearTimeout(greenTimerRef.current);
      }
    },
    [],
  );

  if (!rulesIntegrity || bannerPhase === "none") {
    return null;
  }

  const bannerBody =
    bannerPhase === "green" ? (
      <div className={styles.integrityAlertSuccess}>
        <div className={styles.integrityAlertMain}>
          <span className={styles.integrityAlertSuccessIcon}>✓</span>
          <span className={styles.integrityAlertTitle}>
            {t("security.rulesIntegrity.autoRepairCompletedTitle", {
              defaultValue: "已自动修复完成，工具禁用已解除",
            })}
          </span>
        </div>
      </div>
    ) : (
      <div className={styles.integrityAlert}>
        <div className={styles.integrityAlertMain}>
          <span className={styles.integrityAlertIcon}>!</span>
          <span className={styles.integrityAlertTitle}>
            {resolveRedBannerTitle(rulesIntegrity, t)}
          </span>
        </div>
      </div>
    );

  if (layout === "global") {
    return <div className={styles.host}>{bannerBody}</div>;
  }

  return bannerBody;
}
