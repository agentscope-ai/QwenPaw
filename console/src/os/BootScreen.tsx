/**
 * BootScreen.tsx — QwenPaw OS power-on splash.
 *
 * Shown once when the desktop mounts (entering /os). Displays the brand mark,
 * an indeterminate-feel progress bar, then fades out and hands control to the
 * desktop via onDone. Purely cosmetic — the app is already loaded by the time
 * this renders (App.tsx gates routes on plugin loading).
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Command } from "lucide-react";
import { useOsStyles } from "./useOsStyles";

interface BootScreenProps {
  /** Called after the boot animation (and fade-out) completes. */
  onDone: () => void;
  /** Total visible duration before fade-out, in ms. */
  durationMs?: number;
}

const FADE_MS = 400;

export default function BootScreen({
  onDone,
  durationMs = 2000,
}: BootScreenProps) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const [progress, setProgress] = useState(0);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const start = Date.now();
    // The fade timer is created inside the finish timer, so track it here
    // and clear all three on cleanup — otherwise unmounting mid-fade would
    // still fire onDone (and update state) on a dead component.
    let fade: ReturnType<typeof setTimeout> | undefined;
    const tick = setInterval(() => {
      const pct = Math.min(100, ((Date.now() - start) / durationMs) * 100);
      setProgress(pct);
      if (pct >= 100) clearInterval(tick);
    }, 60);
    const finish = setTimeout(() => {
      setExiting(true);
      fade = setTimeout(onDone, FADE_MS);
    }, durationMs);
    return () => {
      clearInterval(tick);
      clearTimeout(finish);
      if (fade !== undefined) clearTimeout(fade);
    };
  }, [durationMs, onDone]);

  return (
    <div className={cx(styles.boot, exiting && styles.bootExit)}>
      <div className={styles.bootBrand}>
        <Command size={54} strokeWidth={1.6} />
        <div className={styles.bootName}>QwenPaw OS</div>
      </div>
      <div className={styles.bootBar}>
        <div className={styles.bootBarFill} style={{ width: `${progress}%` }} />
      </div>
      <div className={styles.bootHint}>{t("os.booting", "Starting up…")}</div>
    </div>
  );
}
