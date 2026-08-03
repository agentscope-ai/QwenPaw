/**
 * useOsStyles.ts — Desktop OS PoC styling via antd-style createStyles.
 *
 * Uses the existing antd-style stack (no Tailwind CDN) so the shell stays
 * consistent with the console theme system. All chrome colours come from a
 * semantic palette with a dark and a light variant, driven by the console
 * theme (ThemeContext.isDark), so switching the theme restyles the whole
 * shell. Wallpaper-layer pieces (desktop icons, watermark, boot splash)
 * stay constant — they sit on the user-chosen wallpaper, not on a themed
 * surface. Single brand-orange accent (#FF7F16).
 */
import { createStyles } from "antd-style";
import { useTheme } from "../contexts/ThemeContext";

export const ACCENT = "#FF7F16";
/** Legacy bottom-bar height, kept for existing imports. */
export const TASKBAR_H = 56;
/** macOS-style top menu bar height. */
export const MENUBAR_H = 28;
/** Reserved bottom band for the floating Dock. */
export const DOCK_H = 78;

const RADIUS_WINDOW = 14;
const RADIUS_PANEL = 18;
const RADIUS_CONTROL = 9;
const MOTION_FAST = "140ms";
const MOTION_BASE = "220ms";
const MOTION_SPRING = "cubic-bezier(0.22, 1, 0.36, 1)";

/** Semantic colour roles for the OS chrome (dark / light variants below). */
interface OsPalette {
  textStrong: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  textFaint: string;
  /** Text colour on hovered/active chrome controls. */
  hoverText: string;
  winBg: string;
  panelBg: string;
  barBg: string;
  barBgStrong: string;
  cardBg: string;
  floatBg: string;
  floatBgHover: string;
  toastBg: string;
  winCardBg: string;
  overlayBg: string;
  dimBg: string;
  inputBg: string;
  tooltipBg: string;
  sideBg: string;
  hoverBg: string;
  hoverBgStrong: string;
  subtleBg: string;
  faintBg: string;
  contentBg: string;
  border: string;
  borderStrong: string;
  borderSolid: string;
  chipBg: string;
  dockBorder: string;
  dockDivider: string;
  badgeRing: string;
  shadowWindow: string;
  shadowPanel: string;
  shadowFloat: string;
  shadowToast: string;
}

const DARK: OsPalette = {
  textStrong: "#f1f5f9",
  text: "#e2e8f0",
  textSecondary: "#cbd5e1",
  textMuted: "#94a3b8",
  textFaint: "#64748b",
  hoverText: "#fff",
  winBg: "rgba(24, 24, 27, 0.9)",
  panelBg: "rgba(28, 28, 30, 0.94)",
  barBg: "rgba(30, 30, 32, 0.62)",
  barBgStrong: "rgba(24, 24, 27, 0.8)",
  cardBg: "rgba(63, 63, 70, 0.32)",
  floatBg: "rgba(54, 54, 58, 0.58)",
  floatBgHover: "rgba(72, 72, 78, 0.78)",
  toastBg: "rgba(38, 38, 42, 0.9)",
  winCardBg: "rgba(39, 39, 42, 0.72)",
  overlayBg: "rgba(9, 9, 11, 0.62)",
  dimBg: "rgba(9, 9, 11, 0.52)",
  inputBg: "rgba(82, 82, 91, 0.32)",
  tooltipBg: "rgba(28, 28, 30, 0.94)",
  sideBg: "rgba(9, 9, 11, 0.22)",
  hoverBg: "rgba(255, 255, 255, 0.08)",
  hoverBgStrong: "rgba(255, 255, 255, 0.1)",
  subtleBg: "rgba(255, 255, 255, 0.06)",
  faintBg: "rgba(255, 255, 255, 0.03)",
  contentBg: "rgba(255, 255, 255, 0.02)",
  border: "rgba(148, 163, 184, 0.14)",
  borderStrong: "rgba(148, 163, 184, 0.28)",
  borderSolid: "rgba(148, 163, 184, 0.6)",
  chipBg: "rgba(148, 163, 184, 0.14)",
  dockBorder: "rgba(255, 255, 255, 0.12)",
  dockDivider: "rgba(255, 255, 255, 0.16)",
  badgeRing: "rgba(30, 41, 59, 0.9)",
  shadowWindow:
    "0 36px 90px rgba(0, 0, 0, 0.46), 0 12px 30px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
  shadowPanel: "0 28px 70px rgba(0, 0, 0, 0.42)",
  shadowFloat: "0 18px 44px rgba(0, 0, 0, 0.34)",
  shadowToast: "0 18px 46px rgba(0, 0, 0, 0.34)",
};

const LIGHT: OsPalette = {
  textStrong: "#0f172a",
  text: "#1e293b",
  textSecondary: "#475569",
  textMuted: "#64748b",
  textFaint: "#94a3b8",
  hoverText: "#0f172a",
  winBg: "rgba(246, 246, 248, 0.92)",
  panelBg: "rgba(250, 250, 252, 0.94)",
  barBg: "rgba(246, 246, 248, 0.68)",
  barBgStrong: "rgba(246, 246, 248, 0.84)",
  cardBg: "rgba(255, 255, 255, 0.72)",
  floatBg: "rgba(255, 255, 255, 0.6)",
  floatBgHover: "rgba(255, 255, 255, 0.85)",
  toastBg: "rgba(255, 255, 255, 0.92)",
  winCardBg: "rgba(255, 255, 255, 0.78)",
  overlayBg: "rgba(241, 245, 249, 0.72)",
  dimBg: "rgba(241, 245, 249, 0.55)",
  inputBg: "rgba(15, 23, 42, 0.05)",
  tooltipBg: "rgba(255, 255, 255, 0.96)",
  sideBg: "rgba(15, 23, 42, 0.04)",
  hoverBg: "rgba(15, 23, 42, 0.05)",
  hoverBgStrong: "rgba(15, 23, 42, 0.07)",
  subtleBg: "rgba(15, 23, 42, 0.04)",
  faintBg: "rgba(15, 23, 42, 0.03)",
  contentBg: "rgba(15, 23, 42, 0.02)",
  border: "rgba(15, 23, 42, 0.1)",
  borderStrong: "rgba(15, 23, 42, 0.2)",
  borderSolid: "rgba(71, 85, 105, 0.55)",
  chipBg: "rgba(15, 23, 42, 0.07)",
  dockBorder: "rgba(15, 23, 42, 0.08)",
  dockDivider: "rgba(15, 23, 42, 0.12)",
  badgeRing: "#ffffff",
  shadowWindow:
    "0 34px 84px rgba(15, 23, 42, 0.16), 0 10px 28px rgba(15, 23, 42, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.85)",
  shadowPanel: "0 26px 64px rgba(15, 23, 42, 0.14)",
  shadowFloat: "0 16px 42px rgba(15, 23, 42, 0.14)",
  shadowToast: "0 18px 44px rgba(15, 23, 42, 0.13)",
};

/** Stable props objects so antd-style can memoise per theme. */
const DARK_PROPS = { p: DARK };
const LIGHT_PROPS = { p: LIGHT };

const useOsStylesBase = createStyles(({ css }, { p }: { p: OsPalette }) => ({
  desktop: css`
    position: fixed;
    inset: 0;
    overflow: hidden;
    user-select: none;
    color: #f4f4f5;
    background: linear-gradient(135deg, #0b1120 0%, #14162e 50%, #1e1b4b 100%);
    font-family:
      "Inter",
      -apple-system,
      BlinkMacSystemFont,
      "Segoe UI",
      sans-serif;
    isolation: isolate;
    overscroll-behavior: none;
    touch-action: manipulation;
    @media (prefers-reduced-motion: reduce) {
      &,
      & * {
        scroll-behavior: auto !important;
        animation-duration: 1ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 1ms !important;
      }
    }
    @media (max-width: 768px) {
      min-height: 100dvh;
    }
  `,
  iconsGrid: css`
    position: absolute;
    inset: ${MENUBAR_H + 8}px auto 0 0;
    padding: 20px;
    display: grid;
    grid-auto-flow: column;
    grid-template-rows: repeat(auto-fill, 96px);
    gap: 8px;
    z-index: 0;
    align-content: start;
    @media (max-width: 768px) {
      inset: ${MENUBAR_H + 8}px 0 ${DOCK_H + 10}px;
      grid-auto-flow: row;
      grid-template-rows: none;
      grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
      align-content: start;
      overflow-y: auto;
      padding: 16px 12px;
    }
  `,
  desktopIcon: css`
    width: 84px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 7px;
    padding: 9px 6px 8px;
    border-radius: 13px;
    outline: none;
    cursor: pointer;
    transition:
      background ${MOTION_FAST} ease,
      box-shadow ${MOTION_FAST} ease;
    &:hover {
      background: rgba(255, 255, 255, 0.1);
    }
    &:hover > div {
      transform: translateY(-2px) scale(1.035);
      box-shadow:
        0 14px 28px rgba(0, 0, 0, 0.5),
        inset 0 1px 0 rgba(255, 255, 255, 0.4),
        inset 0 -2px 6px rgba(0, 0, 0, 0.28);
    }
    span {
      padding: 2px 6px;
      border-radius: 5px;
      font-size: 12px;
      line-height: 16px;
      text-align: center;
      color: #fafafa;
      background: rgba(9, 9, 11, 0.26);
      text-shadow: 0 1px 3px rgba(0, 0, 0, 0.72);
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.92);
    }
  `,
  desktopIconSelected: css`
    background: rgba(255, 255, 255, 0.16);
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16);
    span {
      background: rgba(0, 102, 255, 0.82);
      color: #fff;
    }
  `,
  iconTile: css`
    width: 52px;
    height: 52px;
    border-radius: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow:
      0 8px 20px rgba(0, 0, 0, 0.45),
      inset 0 1px 0 rgba(255, 255, 255, 0.35),
      inset 0 -2px 6px rgba(0, 0, 0, 0.25);
    transition:
      transform ${MOTION_FAST} ${MOTION_SPRING},
      box-shadow ${MOTION_FAST} ease;
  `,
  windowsLayer: css`
    position: absolute;
    inset: 0;
    z-index: 10;
    pointer-events: none;
  `,
  window: css`
    position: absolute;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: ${RADIUS_WINDOW}px;
    pointer-events: auto;
    outline: none;
    background: ${p.winBg};
    backdrop-filter: saturate(1.18) blur(22px);
    -webkit-backdrop-filter: saturate(1.18) blur(22px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowWindow};
    transition:
      border-color ${MOTION_BASE} ease,
      box-shadow ${MOTION_BASE} ease,
      opacity ${MOTION_BASE} ease;
    &:focus-visible {
      box-shadow:
        ${p.shadowWindow},
        0 0 0 2px rgba(255, 127, 22, 0.74);
    }
  `,
  windowActive: css`
    border-color: rgba(255, 255, 255, 0.24);
    box-shadow:
      ${p.shadowWindow},
      0 0 0 1px rgba(255, 127, 22, 0.12);
  `,
  header: css`
    height: 40px;
    flex: 0 0 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 10px 0 12px;
    background: ${p.barBg};
    border-bottom: 1px solid ${p.border};
    cursor: grab;
    &:active {
      cursor: grabbing;
    }
  `,
  headerTitle: css`
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 500;
    color: ${p.text};
  `,
  headerBtns: css`
    display: flex;
    align-items: center;
    gap: 4px;
  `,
  winBtn: css`
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: ${p.textMuted};
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.12s ease;
    &:hover {
      background: ${p.hoverBgStrong};
      color: ${p.hoverText};
    }
  `,
  winBtnClose: css`
    &:hover {
      background: #ef4444;
      color: #fff;
    }
  `,
  content: css`
    flex: 1;
    overflow: auto;
    position: relative;
    background: ${p.contentBg};
  `,
  resizeHandle: css`
    position: absolute;
    right: 0;
    bottom: 0;
    width: 16px;
    height: 16px;
    cursor: nwse-resize;
    z-index: 5;
    &::after {
      content: "";
      position: absolute;
      right: 3px;
      bottom: 3px;
      width: 7px;
      height: 7px;
      border-right: 2px solid ${p.borderSolid};
      border-bottom: 2px solid ${p.borderSolid};
    }
  `,
  /** Invisible edge/corner resize zones (positioning + cursor set inline). */
  resizeArea: css`
    position: absolute;
    z-index: 5;
  `,
  loading: css`
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  `,
  // ── Taskbar ────────────────────────────────────────────────────────────
  taskbar: css`
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: ${TASKBAR_H}px;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 12px;
    background: ${p.barBgStrong};
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-top: 1px solid ${p.border};
  `,
  startBtn: css`
    width: 40px;
    height: 40px;
    border: none;
    background: transparent;
    color: ${ACCENT};
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.12s ease;
    &:hover {
      background: ${p.hoverBgStrong};
    }
  `,
  taskbarApps: css`
    flex: 1;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 12px;
    overflow-x: auto;
  `,
  taskItem: css`
    height: 40px;
    padding: 0 14px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: ${p.textSecondary};
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 13px;
    max-width: 180px;
    transition: all 0.12s ease;
    &:hover {
      background: ${p.hoverBg};
      color: ${p.hoverText};
    }
    span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
  taskItemActive: css`
    background: ${p.hoverBgStrong};
    color: ${p.hoverText};
    border-bottom: 2px solid ${ACCENT};
  `,
  tray: css`
    display: flex;
    align-items: center;
    gap: 14px;
    color: ${p.textSecondary};
    font-size: 12px;
  `,
  clock: css`
    text-align: right;
    line-height: 1.2;
    .date {
      font-size: 10px;
      color: ${p.textMuted};
    }
  `,
  // ── Launcher ─────────────────────────────────────────────────────────────
  launcher: css`
    position: absolute;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: max(64px, 8vh) clamp(16px, 5vw, 72px) ${DOCK_H + 24}px;
    background: ${p.dimBg};
    backdrop-filter: saturate(1.15) blur(28px);
    -webkit-backdrop-filter: saturate(1.15) blur(28px);
    animation: launcherIn ${MOTION_BASE} ${MOTION_SPRING};
    @keyframes launcherIn {
      from {
        opacity: 0;
      }
      to {
        opacity: 1;
      }
    }
    @media (max-width: 768px) {
      padding: 54px 14px ${DOCK_H + 18}px;
      align-items: flex-start;
    }
  `,
  launcherSurface: css`
    width: min(920px, 100%);
    max-height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
  `,
  launcherSearch: css`
    display: flex;
    align-items: center;
    gap: 10px;
    width: min(420px, 100%);
    min-height: 44px;
    padding: 0 15px;
    margin-bottom: clamp(24px, 5vh, 48px);
    border-radius: 13px;
    color: ${p.textMuted};
    background: ${p.floatBg};
    border: 1px solid ${p.borderStrong};
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14);
    input {
      flex: 1;
      min-width: 0;
      background: transparent;
      border: none;
      outline: none;
      color: ${p.text};
      font-size: 15px;
      &::placeholder {
        color: ${p.textMuted};
      }
    }
    &:focus-within {
      border-color: rgba(255, 255, 255, 0.36);
      box-shadow:
        0 8px 28px rgba(0, 0, 0, 0.14),
        0 0 0 3px rgba(255, 127, 22, 0.18);
    }
  `,
  launcherGrid: css`
    width: 100%;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
    gap: clamp(16px, 3vw, 30px) clamp(12px, 2vw, 24px);
    overflow-y: auto;
    padding: 4px 8px 24px;
    align-content: start;
    @media (max-width: 768px) {
      grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
      gap: 16px 8px;
    }
  `,
  launcherItem: css`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    min-height: 108px;
    padding: 10px 8px;
    border-radius: 15px;
    outline: none;
    cursor: pointer;
    transition:
      background ${MOTION_FAST} ease,
      transform ${MOTION_FAST} ${MOTION_SPRING};
    &:hover {
      background: ${p.subtleBg};
      transform: translateY(-2px);
    }
    span {
      max-width: 120px;
      font-size: 13px;
      line-height: 17px;
      color: ${p.text};
      text-align: center;
      text-shadow: 0 1px 5px rgba(0, 0, 0, 0.28);
    }
    &:focus-visible {
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.72);
    }
  `,
  launcherIcon: css`
    width: 64px;
    height: 64px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow:
      0 12px 24px rgba(0, 0, 0, 0.28),
      inset 0 1px 0 rgba(255, 255, 255, 0.34);
  `,
  launcherEmpty: css`
    grid-column: 1 / -1;
    padding: 48px 16px;
    color: ${p.textSecondary};
    font-size: 14px;
    text-align: center;
  `,
  emptyHint: css`
    position: absolute;
    inset: 0 0 ${TASKBAR_H}px 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
    color: ${ACCENT};
    pointer-events: none;
    opacity: 0.055;
    z-index: 0;
    img {
      width: 88px;
      height: 88px;
      border-radius: 50%;
      object-fit: contain;
      filter: drop-shadow(0 8px 28px rgba(0, 0, 0, 0.4));
    }
  `,
  emptyBrandName: css`
    font-family:
      "Inter",
      -apple-system,
      BlinkMacSystemFont,
      sans-serif;
    font-size: 40px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: #e2e8f0;
    text-shadow: 0 2px 24px rgba(0, 0, 0, 0.4);
  `,
  // ── App Store ─────────────────────────────────────────────────────────────
  storeRoot: css`
    display: flex;
    flex-direction: column;
    height: 100%;
    color: ${p.text};
  `,
  storeHead: css`
    padding: 20px 24px 12px;
    h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 600;
    }
    p {
      margin: 4px 0 0;
      font-size: 13px;
      color: ${p.textMuted};
    }
  `,
  storeToolbar: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px 12px;
    border-bottom: 1px solid ${p.border};
  `,
  storeBody: css`
    flex: 1;
    overflow-y: auto;
    padding: 8px 0 20px;
  `,
  storeGrid: css`
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 14px;
    padding: 8px 24px 4px;
    align-content: start;
  `,
  storeCard: css`
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border-radius: 14px;
    background: ${p.cardBg};
    border: 1px solid ${p.border};
    transition: border-color 0.15s ease;
    &:hover {
      border-color: rgba(255, 127, 22, 0.35);
    }
  `,
  storeCardTop: css`
    display: flex;
    align-items: center;
    gap: 12px;
    .meta {
      min-width: 0;
    }
    .name {
      font-size: 14px;
      font-weight: 600;
    }
    .status {
      font-size: 11px;
      margin-top: 2px;
    }
  `,
  storeTile: css`
    width: 44px;
    height: 44px;
    flex: 0 0 44px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
  `,
  storeBtn: css`
    height: 32px;
    border: 1px solid ${p.borderStrong};
    background: transparent;
    color: ${p.text};
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.12s ease;
    &:hover {
      background: ${p.hoverBg};
    }
  `,
  storeBtnInstall: css`
    border-color: ${ACCENT};
    color: ${ACCENT};
    &:hover {
      background: rgba(255, 127, 22, 0.14);
    }
  `,
  storeSectionTitle: css`
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 16px 24px 2px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: ${p.textMuted};
  `,
  storeEmpty: css`
    padding: 14px 24px;
    color: ${p.textFaint};
    font-size: 13px;
  `,
  pluginBadge: css`
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    background: ${p.chipBg};
    color: ${p.textSecondary};
  `,
  storeToolbarRow: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 12px 24px 4px;
    flex-wrap: wrap;
  `,
  storeChips: css`
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  `,
  storeChip: css`
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 12px;
    cursor: pointer;
    color: ${p.textSecondary};
    background: ${p.chipBg};
    border: 1px solid transparent;
    transition: all 0.12s ease;
    &:hover {
      background: ${p.hoverBg};
    }
  `,
  storeChipActive: css`
    background: rgba(255, 127, 22, 0.16);
    border-color: ${ACCENT};
    color: ${p.hoverText};
  `,
  storeCardDesc: css`
    font-size: 12px;
    color: ${p.textMuted};
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.4em;
  `,
  storeCardMeta: css`
    font-size: 11px;
    color: ${p.textFaint};
    margin-top: 4px;
  `,
  storeActions: css`
    display: flex;
    gap: 8px;
    align-items: center;
  `,
  storePager: css`
    display: flex;
    justify-content: center;
    padding: 14px 0 4px;
  `,
  // ── Mission Control (Spaces switcher) ──────────────────────────────
  mcOverlay: css`
    position: absolute;
    inset: 0;
    z-index: 80;
    display: flex;
    flex-direction: column;
    padding: clamp(20px, 4vw, 48px);
    gap: 20px;
    background: ${p.overlayBg};
    backdrop-filter: saturate(1.1) blur(26px);
    -webkit-backdrop-filter: saturate(1.1) blur(26px);
    animation: mcFade ${MOTION_BASE} ease-out;
    @keyframes mcFade {
      from {
        opacity: 0;
      }
      to {
        opacity: 1;
      }
    }
    @media (max-width: 768px) {
      padding: 48px 14px ${DOCK_H + 18}px;
      gap: 14px;
    }
  `,
  mcSpaces: css`
    display: flex;
    align-items: center;
    gap: 14px;
    overflow-x: auto;
    padding: 4px 2px 12px;
    justify-content: center;
    flex-wrap: wrap;
  `,
  mcSpaceCard: css`
    width: 176px;
    height: 104px;
    border-radius: ${RADIUS_WINDOW}px;
    background: ${p.floatBg};
    border: 2px solid transparent;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    cursor: pointer;
    outline: none;
    transition:
      background ${MOTION_FAST} ease,
      border-color ${MOTION_FAST} ease,
      transform ${MOTION_FAST} ${MOTION_SPRING};
    color: ${p.text};
    &:hover {
      background: ${p.floatBgHover};
      transform: translateY(-2px);
    }
    &:focus-visible {
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.72);
    }
    .avatar {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      color: #fff;
    }
    .name {
      font-size: 13px;
      font-weight: 500;
      max-width: 150px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .count {
      font-size: 11px;
      color: ${p.textMuted};
    }
    @media (max-width: 768px) {
      width: 142px;
      height: 94px;
    }
  `,
  mcSpaceActive: css`
    border-color: ${ACCENT};
    background: rgba(255, 127, 22, 0.1);
  `,
  mcSpaceAdd: css`
    width: 56px;
    height: 104px;
    border-radius: ${RADIUS_WINDOW}px;
    border: 2px dashed ${p.borderStrong};
    background: transparent;
    color: ${p.textMuted};
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    outline: none;
    transition:
      border-color ${MOTION_FAST} ease,
      transform ${MOTION_FAST} ${MOTION_SPRING},
      box-shadow ${MOTION_FAST} ease;
    &:hover {
      border-color: ${ACCENT};
      color: ${ACCENT};
    }
  `,
  mcWindows: css`
    flex: 1;
    overflow-y: auto;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 16px;
    align-content: start;
    padding-top: 12px;
    border-top: 1px solid ${p.border};
  `,
  mcWindowCard: css`
    height: 130px;
    border-radius: 12px;
    background: ${p.winCardBg};
    border: 1px solid ${p.border};
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    cursor: pointer;
    transition: all 0.15s ease;
    color: ${p.text};
    &:hover {
      border-color: ${ACCENT};
      transform: translateY(-2px);
    }
    &:focus-visible {
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.72);
    }
    .title {
      font-size: 13px;
      font-weight: 500;
    }
  `,
  mcHint: css`
    text-align: center;
    color: ${p.textFaint};
    font-size: 13px;
    padding: 40px 0;
  `,
  // ── macOS traffic lights (window header, left side) ───────────────────
  headerMac: css`
    height: 42px;
    flex: 0 0 42px;
    display: flex;
    align-items: center;
    padding: 0 13px;
    background: ${p.barBg};
    border-bottom: 1px solid ${p.border};
    cursor: grab;
    transition:
      background ${MOTION_BASE} ease,
      color ${MOTION_BASE} ease;
    &:active {
      cursor: grabbing;
    }
    &[data-active="false"] {
      opacity: 0.86;
    }
  `,
  lights: css`
    display: flex;
    align-items: center;
    gap: 2px;
    width: 76px;
    height: 40px;
  `,
  light: css`
    position: relative;
    width: 24px;
    height: 34px;
    border-radius: 8px;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(0, 0, 0, 0.55);
    background: transparent;
    outline: none;
    &::before {
      content: "";
      position: absolute;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--traffic-light-color);
      box-shadow: inset 0 0 0 0.5px rgba(0, 0, 0, 0.18);
    }
    svg {
      position: relative;
      z-index: 1;
      opacity: 0;
      transition: opacity ${MOTION_FAST} ease;
    }
    &:hover svg {
      opacity: 1;
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px ${ACCENT};
    }
    &:disabled {
      cursor: default;
      opacity: 0.55;
    }
  `,
  lightClose: css`
    --traffic-light-color: #ff5f57;
  `,
  lightMin: css`
    --traffic-light-color: #febc2e;
  `,
  lightMax: css`
    --traffic-light-color: #28c840;
  `,
  macTitle: css`
    flex: 1;
    text-align: center;
    min-width: 0;
    font-size: 12.5px;
    font-weight: 600;
    color: ${p.text};
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  `,
  // ── macOS top menu bar ──────────────────────────────────────
  menubar: css`
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: ${MENUBAR_H}px;
    z-index: 55;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 10px 0 12px;
    background: ${p.barBg};
    backdrop-filter: saturate(1.2) blur(20px);
    -webkit-backdrop-filter: saturate(1.2) blur(20px);
    border-bottom: 1px solid ${p.border};
    font-size: 12px;
    color: ${p.text};
  `,
  menubarLeft: css`
    display: flex;
    align-items: center;
    min-width: 0;
    gap: 4px;
  `,
  menubarBrand: css`
    display: flex;
    align-items: center;
    width: 24px;
    height: 24px;
    padding: 2px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    cursor: pointer;
    outline: none;
    img {
      width: 20px;
      height: 20px;
      display: block;
      border-radius: 50%;
    }
    &:hover {
      background: ${p.hoverBg};
    }
    &:focus-visible {
      box-shadow: inset 0 0 0 2px ${ACCENT};
    }
  `,
  menubarName: css`
    min-height: 24px;
    max-width: 180px;
    display: inline-flex;
    align-items: center;
    padding: 0 8px;
    border-radius: 6px;
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
    outline: none;
    &:hover {
      background: ${p.hoverBg};
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px ${ACCENT};
    }
  `,
  menubarItem: css`
    max-width: 180px;
    min-height: 24px;
    display: inline-flex;
    align-items: center;
    padding: 0 8px;
    border-radius: 6px;
    color: ${p.textSecondary};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  menubarRight: css`
    display: flex;
    align-items: center;
    gap: 3px;
    color: ${p.textSecondary};
    @media (max-width: 768px) {
      > svg {
        display: none;
      }
    }
  `,
  menubarBtn: css`
    display: flex;
    align-items: center;
    background: none;
    border: none;
    color: ${p.textSecondary};
    cursor: pointer;
    min-width: 28px;
    height: 28px;
    justify-content: center;
    padding: 0 6px;
    border-radius: 6px;
    outline: none;
    &:hover {
      background: ${p.hoverBg};
      color: ${p.hoverText};
    }
    &:focus-visible {
      box-shadow: inset 0 0 0 2px ${ACCENT};
      color: ${p.hoverText};
    }
  `,
  // ── macOS Dock ───────────────────────────────────────────
  dock: css`
    position: absolute;
    left: 50%;
    bottom: 10px;
    transform: translateX(-50%);
    z-index: 50;
    display: flex;
    align-items: flex-end;
    gap: 6px;
    max-width: calc(100vw - 20px);
    padding: 7px 10px 9px;
    border-radius: ${RADIUS_PANEL}px;
    background: ${p.floatBg};
    backdrop-filter: saturate(1.24) blur(24px);
    -webkit-backdrop-filter: saturate(1.24) blur(24px);
    border: 1px solid ${p.dockBorder};
    box-shadow: ${p.shadowFloat};
    overflow-x: auto;
    overflow-y: visible;
    scrollbar-width: none;
    &::-webkit-scrollbar {
      display: none;
    }
    transition:
      transform ${MOTION_BASE} ${MOTION_SPRING},
      opacity ${MOTION_BASE} ease;
    @media (max-width: 768px) {
      gap: 4px;
      bottom: max(8px, env(safe-area-inset-bottom));
      padding: 6px 8px 8px;
    }
  `,
  dockHidden: css`
    transform: translateX(-50%) translateY(140%);
    opacity: 0;
    pointer-events: none;
  `,
  dockDropActive: css`
    border-color: ${ACCENT};
    box-shadow:
      0 0 0 3px rgba(255, 127, 22, 0.22),
      ${p.shadowFloat};
  `,
  dockItem: css`
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 0 0 auto;
    min-width: 48px;
    min-height: 52px;
    justify-content: flex-end;
    border-radius: 13px;
    outline: none;
    cursor: pointer;
    transition: transform ${MOTION_FAST} ${MOTION_SPRING};
    transform-origin: bottom center;
    &:hover {
      transform: scale(1.18) translateY(-5px);
    }
    &:focus-visible {
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.78);
    }
    @media (max-width: 768px) {
      min-width: 44px;
      min-height: 48px;
      &:hover {
        transform: none;
      }
    }
  `,
  dockItemDragging: css`
    opacity: 0.62;
    transform: scale(1.12) translateY(-8px);
  `,
  dockIcon: css`
    width: 48px;
    height: 48px;
    border-radius: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow:
      0 7px 16px rgba(0, 0, 0, 0.28),
      inset 0 1px 0 rgba(255, 255, 255, 0.28);
    @media (max-width: 768px) {
      width: 44px;
      height: 44px;
      border-radius: 12px;
    }
  `,
  dockDot: css`
    position: absolute;
    bottom: -5px;
    left: 50%;
    transform: translateX(-50%);
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: ${p.textStrong};
  `,
  dockTooltip: css`
    position: absolute;
    bottom: 66px;
    left: 50%;
    transform: translateX(-50%);
    padding: 5px 9px;
    border-radius: 7px;
    background: ${p.tooltipBg};
    border: 1px solid ${p.borderStrong};
    color: ${p.text};
    font-size: 12px;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    box-shadow: ${p.shadowFloat};
    transition: opacity ${MOTION_FAST} ease;
  `,
  dockDivider: css`
    width: 1px;
    height: 42px;
    margin: 0 4px;
    background: ${p.dockDivider};
  `,
  dockBadge: css`
    position: absolute;
    top: -2px;
    right: -2px;
    min-width: 18px;
    height: 18px;
    padding: 0 4px;
    border-radius: 9px;
    background: #ef4444;
    color: #fff;
    font-size: 11px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 2px solid ${p.badgeRing};
  `,
  dockDropMarker: css`
    position: absolute;
    left: -5px;
    bottom: 5px;
    width: 3px;
    height: 40px;
    border-radius: 2px;
    background: ${ACCENT};
    box-shadow: 0 0 12px ${ACCENT};
  `,
  // ── Menu-bar notification entry ────────────────────────────
  notificationMenuButton: css`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    min-width: 28px;
    height: 28px;
    padding: 0 6px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: ${p.textSecondary};
    cursor: pointer;
    outline: none;
    &:hover {
      background: ${p.hoverBg};
      color: ${p.hoverText};
    }
    &:focus-visible {
      box-shadow: inset 0 0 0 2px ${ACCENT};
      color: ${p.hoverText};
    }
  `,
  notificationMenuCount: css`
    font-size: 11px;
    line-height: 1;
    font-weight: 600;
    color: currentColor;
    font-variant-numeric: tabular-nums;
  `,
  // ── Notification toasts (top-right banners) ─────────────────────
  toastStack: css`
    position: absolute;
    top: ${MENUBAR_H + 12}px;
    right: 14px;
    z-index: 70;
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 340px;
    max-width: calc(100vw - 28px);
    pointer-events: none;
  `,
  toast: css`
    pointer-events: auto;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px;
    border-radius: ${RADIUS_PANEL}px;
    cursor: pointer;
    background: ${p.toastBg};
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowToast};
    transition: transform ${MOTION_FAST} ${MOTION_SPRING};
    &:hover {
      transform: scale(1.01);
    }
  `,
  toastEnter: css`
    @keyframes osToastIn {
      from {
        opacity: 0;
        transform: translateX(24px);
      }
      to {
        opacity: 1;
        transform: translateX(0);
      }
    }
    animation: osToastIn 0.24s cubic-bezier(0.2, 0.8, 0.2, 1);
  `,
  toastIcon: css`
    flex: 0 0 auto;
    width: 30px;
    height: 30px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${p.subtleBg};
  `,
  toastBody: css`
    flex: 1;
    min-width: 0;
  `,
  toastTitle: css`
    font-size: 13px;
    font-weight: 600;
    color: ${p.textStrong};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  toastText: css`
    font-size: 12px;
    color: ${p.textSecondary};
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  `,
  toastMeta: css`
    font-size: 10px;
    color: ${p.textMuted};
    margin-top: 4px;
  `,
  toastClose: css`
    flex: 0 0 auto;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    color: ${p.textMuted};
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    &:hover {
      background: ${p.hoverBgStrong};
      color: ${p.hoverText};
    }
  `,
  // Quick approve/deny actions on approval notifications.
  notifyActions: css`
    display: flex;
    gap: 8px;
    margin-top: 8px;
  `,
  notifyApproveBtn: css`
    flex: 1;
    height: 28px;
    border: none;
    border-radius: 8px;
    background: ${ACCENT};
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    &:hover {
      filter: brightness(1.05);
    }
    &:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `,
  notifyDenyBtn: css`
    flex: 1;
    height: 28px;
    border: 1px solid ${p.borderStrong};
    border-radius: 8px;
    background: transparent;
    color: ${p.text};
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    &:hover {
      background: ${p.hoverBg};
    }
    &:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `,
  // ── Notification Center panel ───────────────────────────────
  ncPanel: css`
    position: absolute;
    top: ${MENUBAR_H + 8}px;
    right: 10px;
    bottom: 10px;
    width: 340px;
    max-width: calc(100vw - 20px);
    z-index: 65;
    display: flex;
    flex-direction: column;
    border-radius: ${RADIUS_PANEL}px;
    background: ${p.panelBg};
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowPanel};
    overflow: hidden;
    @media (max-width: 768px) {
      top: ${MENUBAR_H + 6}px;
      right: 6px;
      bottom: max(8px, env(safe-area-inset-bottom));
      width: calc(100vw - 12px);
      max-width: none;
    }
  `,
  ncHeader: css`
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border-bottom: 1px solid ${p.border};
  `,
  ncTitle: css`
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    font-weight: 600;
    color: ${p.textStrong};
  `,
  ncIconBtn: css`
    width: 36px;
    height: 36px;
    border: none;
    background: transparent;
    color: ${p.textMuted};
    border-radius: ${RADIUS_CONTROL}px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    outline: none;
    &:hover {
      background: ${p.hoverBgStrong};
      color: ${p.hoverText};
    }
    &:focus-visible {
      box-shadow: inset 0 0 0 2px ${ACCENT};
    }
  `,
  ncList: css`
    flex: 1;
    overflow-y: auto;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  `,
  ncEmpty: css`
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: ${p.textFaint};
    font-size: 13px;
    padding: 40px 0;
  `,
  ncItem: css`
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px;
    border-radius: 12px;
    cursor: pointer;
    outline: none;
    background: ${p.faintBg};
    transition: background 0.12s ease;
    &:hover {
      background: ${p.hoverBg};
    }
    &:focus-visible {
      box-shadow: inset 0 0 0 2px ${ACCENT};
    }
  `,
  ncItemIcon: css`
    flex: 0 0 auto;
    width: 26px;
    height: 26px;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${p.subtleBg};
  `,
  ncItemBody: css`
    flex: 1;
    min-width: 0;
  `,
  ncItemTitle: css`
    font-size: 13px;
    font-weight: 600;
    color: ${p.text};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  ncItemText: css`
    font-size: 12px;
    color: ${p.textMuted};
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  `,
  ncItemTime: css`
    flex: 0 0 auto;
    font-size: 10px;
    color: ${p.textFaint};
  `,
  // ── System Settings app (macOS-style aggregate) ───────────────────
  settingsRoot: css`
    display: flex;
    height: 100%;
  `,
  settingsSidebar: css`
    flex: 0 0 220px;
    width: 220px;
    overflow-y: auto;
    padding: 10px;
    border-right: 1px solid ${p.border};
    background: ${p.sideBg};
  `,
  settingsNavItem: css`
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 12px;
    border-radius: 8px;
    cursor: pointer;
    color: ${p.textSecondary};
    font-size: 13px;
    margin-bottom: 2px;
    transition: background 0.12s ease;
    &:hover {
      background: ${p.subtleBg};
    }
  `,
  settingsNavActive: css`
    background: rgba(255, 127, 22, 0.16);
    color: ${p.hoverText};
  `,
  settingsPane: css`
    flex: 1;
    overflow: auto;
    position: relative;
  `,
  // ── Boot / power-on splash ────────────────────────────────────────
  boot: css`
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 26px;
    background: radial-gradient(
      120% 120% at 50% 40%,
      #14162e 0%,
      #0b1120 60%,
      #05070f 100%
    );
    color: #e2e8f0;
    animation: bootFadeIn 0.4s ease-out;
    @keyframes bootFadeIn {
      from {
        opacity: 0;
      }
      to {
        opacity: 1;
      }
    }
  `,
  bootExit: css`
    animation: bootFadeOut 0.4s ease-in forwards;
    @keyframes bootFadeOut {
      from {
        opacity: 1;
      }
      to {
        opacity: 0;
      }
    }
  `,
  bootBrand: css`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    color: ${ACCENT};
    animation: bootPulse 2s ease-in-out infinite;
    @keyframes bootPulse {
      0%,
      100% {
        opacity: 0.85;
        transform: scale(1);
      }
      50% {
        opacity: 1;
        transform: scale(1.04);
      }
    }
  `,
  bootName: css`
    font-family:
      "Inter",
      -apple-system,
      BlinkMacSystemFont,
      sans-serif;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #f1f5f9;
  `,
  bootBar: css`
    width: 220px;
    height: 4px;
    border-radius: 999px;
    overflow: hidden;
    background: rgba(148, 163, 184, 0.18);
  `,
  bootBarFill: css`
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, ${ACCENT}, #ffb066);
    transition: width 0.12s linear;
  `,
  bootHint: css`
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748b;
  `,
  // ── Desktop right-click context menu ───────────────────────────────
  desktopMenuAnchor: css`
    position: fixed;
    z-index: 90;
    width: 1px;
    height: 1px;
    pointer-events: none;
  `,
  desktopContextMenu: css`
    .ant-dropdown-menu {
      min-width: 190px;
      padding: 6px;
      border: 1px solid ${p.border};
      border-radius: 12px;
      background: ${p.panelBg};
      box-shadow: ${p.shadowPanel};
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
    }
    .ant-dropdown-menu-item,
    .ant-dropdown-menu-submenu-title {
      min-height: 36px;
      border-radius: 7px;
    }
  `,
  // ── Wallpaper picker overlay ───────────────────────────────────────
  wpOverlay: css`
    position: absolute;
    inset: 0;
    z-index: 95;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${p.dimBg};
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    animation: bootFadeIn 0.16s ease-out;
  `,
  wpPanel: css`
    width: min(560px, 92vw);
    max-height: 76vh;
    display: flex;
    flex-direction: column;
    border-radius: 16px;
    background: ${p.panelBg};
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowPanel};
    overflow: hidden;
  `,
  wpHead: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    font-size: 14px;
    font-weight: 600;
    color: ${p.textStrong};
    border-bottom: 1px solid ${p.border};
  `,
  wpClose: css`
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: ${p.textMuted};
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    &:hover {
      background: ${p.hoverBgStrong};
      color: ${p.hoverText};
    }
  `,
  wpGrid: css`
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    padding: 16px;
    overflow-y: auto;
  `,
  wpItem: css`
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 4px;
    border-radius: 13px;
    cursor: pointer;
    outline: none;
    span {
      font-size: 12px;
      color: ${p.textSecondary};
      text-align: center;
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px ${ACCENT};
    }
  `,
  wpItemActive: css`
    span {
      color: ${p.hoverText};
      font-weight: 600;
    }
  `,
  wpSwatch: css`
    height: 78px;
    border-radius: 12px;
    border: 2px solid transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
    transition: border-color 0.12s ease;
  `,
  // ── Auto-hide chrome + Spaces panel + snapping + icon drag ──────────
  menubarHidden: css`
    transform: translateY(-100%);
    opacity: 0;
    pointer-events: none;
    transition:
      transform 0.22s ease,
      opacity 0.22s ease;
  `,
  menubarShown: css`
    transform: translateY(0);
    opacity: 1;
    transition:
      transform 0.22s ease,
      opacity 0.22s ease;
  `,
  spacesPanel: css`
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 14px;
    padding: 12px 18px;
    background: ${p.barBgStrong};
    backdrop-filter: saturate(1.2) blur(22px);
    -webkit-backdrop-filter: saturate(1.2) blur(22px);
    border-bottom: 1px solid ${p.border};
    transform: translateY(0);
    transition:
      transform ${MOTION_BASE} ${MOTION_SPRING},
      opacity ${MOTION_BASE} ease;
  `,
  spacesPanelHidden: css`
    transform: translateY(-100%);
    opacity: 0;
    pointer-events: none;
  `,
  spaceChip: css`
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px 6px 6px;
    border-radius: 999px;
    cursor: pointer;
    border: 1px solid transparent;
    outline: none;
    transition:
      background ${MOTION_FAST} ease,
      border-color ${MOTION_FAST} ease;
    &:hover {
      background: ${p.hoverBg};
    }
    &:focus-visible {
      box-shadow: 0 0 0 2px ${ACCENT};
    }
    .avatar {
      width: 30px;
      height: 30px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      font-weight: 700;
      font-size: 14px;
    }
    .name {
      font-size: 13px;
      color: ${p.text};
      white-space: nowrap;
    }
  `,
  spaceChipActive: css`
    border-color: ${ACCENT};
    background: rgba(255, 127, 22, 0.14);
  `,
  snapPreview: css`
    position: absolute;
    z-index: 9;
    border-radius: ${RADIUS_WINDOW}px;
    background: rgba(255, 127, 22, 0.18);
    border: 2px solid ${ACCENT};
    pointer-events: none;
    transition:
      left 0.12s ease,
      top 0.12s ease,
      width 0.12s ease,
      height 0.12s ease;
  `,
  /** Positioning layer only — lets clicks on empty desktop reach the root
   *  (context menu / wallpaper). Icons re-enable pointer events below. */
  iconsLayer: css`
    position: absolute;
    inset: 0;
    z-index: 0;
    pointer-events: none;
  `,
  iconAbsolute: css`
    position: absolute;
    pointer-events: auto;
    touch-action: none;
  `,
  windowMinimizing: css`
    transform: scale(0.2) translateY(60vh);
    opacity: 0;
    transition:
      transform ${MOTION_BASE} ease-in,
      opacity ${MOTION_BASE} ease-in;
    transform-origin: bottom center;
  `,
  reducedMotion: css`
    @media (prefers-reduced-motion: reduce) {
      animation: none !important;
      transition-duration: 1ms !important;
    }
  `,
}));

/**
 * Theme-aware wrapper: resolves the OS palette from the console theme so
 * every chrome piece restyles when the user switches light/dark. Call sites
 * keep the original `useOsStyles()` signature.
 */
export function useOsStyles() {
  const { isDark } = useTheme();
  return useOsStylesBase(isDark ? DARK_PROPS : LIGHT_PROPS);
}
