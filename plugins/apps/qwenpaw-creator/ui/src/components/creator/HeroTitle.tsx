import { useTranslation } from "react-i18next";
import wordmarkUrl from "@/assets/design/wordmark-qwenpaw.svg";
import cursorDirector from "@/assets/design/cursor-director.svg";
import cursorWriter from "@/assets/design/cursor-writer.svg";
import cursorMotion from "@/assets/design/cursor-motion.svg";
import cursorEditor from "@/assets/design/cursor-editor.svg";

/**
 * Hero title transcribed 1:1 from the design draft (1440x900 artboard).
 * Cursor offsets are relative to the 508.94x82 title row at (465.5, 214);
 * anchors were re-sampled because the D2C export wraps two groups in a
 * spurious `rotate(180deg)`.
 */

const TITLE_ROW_WIDTH = 508.94;
const TITLE_ROW_HEIGHT = 82;

interface RoleCursor {
  label: string;
  color: string;
  /** Pill anchor, relative to the title row box. */
  pill: React.CSSProperties;
  /** Cursor arrow anchor, relative to the pill wrapper. */
  arrow: React.CSSProperties;
  icon: string;
  delay: string;
}

const ROLE_CURSORS: (Omit<RoleCursor, "label"> & { labelKey: string })[] = [
  {
    labelKey: "home.heroTitleDirector",
    color: "#F4C21C",
    pill: { left: -102.5, top: 54 },
    arrow: { left: 50, top: -4 },
    icon: cursorDirector,
    delay: "0s",
  },
  {
    labelKey: "home.heroTitleWriter",
    color: "#F6851C",
    pill: { left: -29.5, top: -34 },
    arrow: { left: 44, top: 19 },
    icon: cursorWriter,
    delay: "1.2s",
  },
  {
    labelKey: "home.heroTitleEffects",
    color: "#5385FA",
    pill: { right: -51.6, top: -62 },
    arrow: { right: 56, top: 20 },
    icon: cursorMotion,
    delay: "2.1s",
  },
  {
    labelKey: "home.heroTitleEditor",
    color: "#FCB900",
    pill: { right: -105.6, top: 54 },
    arrow: { right: 42, top: -12 },
    icon: cursorEditor,
    delay: "0.7s",
  },
];

export default function HeroTitle() {
  const { t } = useTranslation();
  return (
    <div
      className="relative"
      style={{ width: TITLE_ROW_WIDTH, height: TITLE_ROW_HEIGHT }}
    >
      <h1
        className="flex items-center justify-center"
        style={{ gap: 10.94, height: TITLE_ROW_HEIGHT, margin: 0 }}
      >
        <img
          src={wordmarkUrl}
          alt="QwenPaw"
          width={279.95}
          height={47.99}
          className="shrink-0"
        />
        <span className="hero-title-creator">Creator</span>
      </h1>

      {ROLE_CURSORS.map((role) => (
        <span
          key={role.labelKey}
          className="hero-role-tag"
          style={{ ...role.pill, animationDelay: role.delay }}
          aria-hidden="true"
        >
          <span className="hero-role-pill" style={{ background: role.color }}>
            {t(role.labelKey)}
          </span>
          <img
            src={role.icon}
            alt=""
            width={15}
            height={15}
            className="hero-role-cursor"
            style={role.arrow}
          />
        </span>
      ))}
    </div>
  );
}
