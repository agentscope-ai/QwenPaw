import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ToolGuardRulesIntegrity } from "../api/client";
import styles from "@/pages/Settings/Security/index.module.less";

const MIN_RED_DISPLAY_MS = 5000;
const DEFAULT_TIMEOUT_MAX = 5;

interface RuleIntegrityRepairBannerProps {
  rulesIntegrity: ToolGuardRulesIntegrity | null;
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

    if (isRedIntegrityState(rulesIntegrity)) {
      if (redStartedAtRef.current === null) {
        redStartedAtRef.current = Date.now();
      }
      setBannerPhase("red");
      return;
    }

    if (isGreenIntegrityState(rulesIntegrity)) {
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
      return;
    }

    setBannerPhase("none");
    redStartedAtRef.current = null;
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

  if (bannerPhase === "green") {
    return (
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
    );
  }

  return (
    <div className={styles.integrityAlert}>
      <div className={styles.integrityAlertMain}>
        <span className={styles.integrityAlertIcon}>!</span>
        <span className={styles.integrityAlertTitle}>
          {resolveRedBannerTitle(rulesIntegrity, t)}
        </span>
      </div>
    </div>
  );
}
