import { useEffect, useState, type ReactNode } from "react";
import api from "@/api";
import type { IntegrityProtectionSettings } from "@/api/modules/security";
import {
  FileBaselineProtectionProvider,
  useFileBaselineProtectionContext,
} from "./FileBaselineProtectionSection";

export interface IntegrityProtectionFrameProps {
  highlightAlertId?: string;
  onAlertCountChange?: (count: number) => void;
  children: (ctx: {
    settings: IntegrityProtectionSettings | null;
    setSettings: (settings: IntegrityProtectionSettings) => void;
  }) => ReactNode;
}

function IntegrityCheckPersonaLoader({
  settings,
  setSettings,
  children,
}: {
  settings: IntegrityProtectionSettings | null;
  setSettings: (settings: IntegrityProtectionSettings) => void;
  children: (ctx: {
    settings: IntegrityProtectionSettings | null;
    setSettings: (settings: IntegrityProtectionSettings) => void;
  }) => ReactNode;
}) {
  const { loadFileBaselineData } = useFileBaselineProtectionContext();

  useEffect(() => {
    Promise.all([
      api.getIntegrityProtectionSettings().then(setSettings),
      loadFileBaselineData(),
    ]).catch(() => {
      setSettings({
        file_baseline_enabled: false,
        health_check_enabled: false,
        rule_integrity_check_passive: true,
        protected_paths: [],
        menus: ["Tool Guard", "File Guard", "Integrity Check", "Health Check"],
      });
    });
  }, [loadFileBaselineData, setSettings]);

  return <>{children({ settings, setSettings })}</>;
}

export function IntegrityProtectionFrame({
  highlightAlertId,
  onAlertCountChange,
  children,
}: IntegrityProtectionFrameProps) {
  const [settings, setSettings] = useState<IntegrityProtectionSettings | null>(
    null,
  );

  return (
    <FileBaselineProtectionProvider
      highlightAlertId={highlightAlertId}
      onAlertCountChange={onAlertCountChange}
      onIntegritySettingsSync={setSettings}
    >
      <IntegrityCheckPersonaLoader settings={settings} setSettings={setSettings}>
        {children}
      </IntegrityCheckPersonaLoader>
    </FileBaselineProtectionProvider>
  );
}
