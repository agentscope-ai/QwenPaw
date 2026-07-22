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
  winBg: "rgba(15, 23, 42, 0.86)",
  panelBg: "rgba(15, 23, 42, 0.95)",
  barBg: "rgba(2, 6, 23, 0.58)",
  barBgStrong: "rgba(2, 6, 23, 0.72)",
  cardBg: "rgba(2, 6, 23, 0.45)",
  floatBg: "rgba(30, 41, 59, 0.55)",
  floatBgHover: "rgba(30, 41, 59, 0.8)",
  toastBg: "rgba(30, 41, 59, 0.92)",
  winCardBg: "rgba(15, 23, 42, 0.7)",
  overlayBg: "rgba(2, 6, 23, 0.72)",
  dimBg: "rgba(2, 6, 23, 0.5)",
  inputBg: "rgba(2, 6, 23, 0.6)",
  tooltipBg: "rgba(2, 6, 23, 0.9)",
  sideBg: "rgba(2, 6, 23, 0.3)",
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
    "0 30px 70px rgba(0, 0, 0, 0.62), 0 10px 24px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
  shadowPanel: "0 24px 60px rgba(0, 0, 0, 0.6)",
  shadowFloat: "0 12px 40px rgba(0, 0, 0, 0.5)",
  shadowToast: "0 14px 40px rgba(0, 0, 0, 0.5)",
};

const LIGHT: OsPalette = {
  textStrong: "#0f172a",
  text: "#1e293b",
  textSecondary: "#475569",
  textMuted: "#64748b",
  textFaint: "#94a3b8",
  hoverText: "#0f172a",
  winBg: "rgba(250, 250, 252, 0.9)",
  panelBg: "rgba(255, 255, 255, 0.95)",
  barBg: "rgba(255, 255, 255, 0.65)",
  barBgStrong: "rgba(255, 255, 255, 0.78)",
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
    "0 30px 70px rgba(15, 23, 42, 0.18), 0 10px 24px rgba(15, 23, 42, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.7)",
  shadowPanel: "0 24px 60px rgba(15, 23, 42, 0.16)",
  shadowFloat: "0 12px 40px rgba(15, 23, 42, 0.15)",
  shadowToast: "0 14px 40px rgba(15, 23, 42, 0.15)",
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
    color: #e2e8f0;
    background: linear-gradient(135deg, #0b1120 0%, #14162e 50%, #1e1b4b 100%);
    font-family:
      "Inter",
      -apple-system,
      BlinkMacSystemFont,
      "Segoe UI",
      sans-serif;
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
  `,
  desktopIcon: css`
    width: 84px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 10px 6px;
    border-radius: 12px;
    cursor: pointer;
    transition: background 0.15s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
    }
    &:hover > div {
      transform: translateY(-3px) scale(1.06);
      box-shadow:
        0 14px 28px rgba(0, 0, 0, 0.5),
        inset 0 1px 0 rgba(255, 255, 255, 0.4),
        inset 0 -2px 6px rgba(0, 0, 0, 0.28);
    }
    span {
      font-size: 12px;
      text-align: center;
      color: #cbd5e1;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
  iconTile: css`
    width: 52px;
    height: 52px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow:
      0 8px 20px rgba(0, 0, 0, 0.45),
      inset 0 1px 0 rgba(255, 255, 255, 0.35),
      inset 0 -2px 6px rgba(0, 0, 0, 0.25);
    transition:
      transform 0.15s ease,
      box-shadow 0.15s ease;
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
    border-radius: 12px;
    pointer-events: auto;
    background: ${p.winBg};
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowWindow};
  `,
  windowActive: css`
    border-color: rgba(255, 127, 22, 0.4);
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
    left: 50%;
    bottom: ${DOCK_H + 12}px;
    transform: translateX(-50%);
    width: min(620px, 92vw);
    max-height: 460px;
    z-index: 60;
    display: flex;
    flex-direction: column;
    padding: 18px;
    border-radius: 16px;
    background: ${p.panelBg};
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowPanel};
  `,
  launcherSearch: css`
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    margin-bottom: 14px;
    border-radius: 10px;
    background: ${p.inputBg};
    border: 1px solid ${p.border};
    input {
      flex: 1;
      background: transparent;
      border: none;
      outline: none;
      color: ${p.text};
      font-size: 14px;
    }
  `,
  launcherGrid: css`
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    overflow-y: auto;
  `,
  launcherItem: css`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 14px 8px;
    border-radius: 12px;
    cursor: pointer;
    transition: background 0.12s ease;
    &:hover {
      background: ${p.subtleBg};
    }
    span {
      font-size: 12px;
      color: ${p.textSecondary};
      text-align: center;
    }
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
    opacity: 0.1;
    z-index: 0;
    svg {
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
    padding: 24px 32px;
    gap: 20px;
    background: ${p.overlayBg};
    backdrop-filter: blur(22px);
    -webkit-backdrop-filter: blur(22px);
    animation: mcFade 0.18s ease-out;
    @keyframes mcFade {
      from {
        opacity: 0;
      }
      to {
        opacity: 1;
      }
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
    border-radius: 12px;
    background: ${p.floatBg};
    border: 2px solid transparent;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    cursor: pointer;
    transition: all 0.15s ease;
    color: ${p.text};
    &:hover {
      background: ${p.floatBgHover};
      transform: translateY(-2px);
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
  `,
  mcSpaceActive: css`
    border-color: ${ACCENT};
    background: rgba(255, 127, 22, 0.1);
  `,
  mcSpaceAdd: css`
    width: 56px;
    height: 104px;
    border-radius: 12px;
    border: 2px dashed ${p.borderStrong};
    background: transparent;
    color: ${p.textMuted};
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.15s ease;
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
    height: 38px;
    flex: 0 0 38px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    background: ${p.barBg};
    border-bottom: 1px solid ${p.border};
    cursor: grab;
    &:active {
      cursor: grabbing;
    }
  `,
  lights: css`
    display: flex;
    align-items: center;
    gap: 8px;
    width: 70px;
  `,
  light: css`
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(0, 0, 0, 0.55);
    svg {
      opacity: 0;
      transition: opacity 0.12s ease;
    }
    &:hover svg {
      opacity: 1;
    }
  `,
  lightClose: css`
    background: #ff5f57;
  `,
  lightMin: css`
    background: #febc2e;
  `,
  lightMax: css`
    background: #28c840;
  `,
  macTitle: css`
    flex: 1;
    text-align: center;
    font-size: 13px;
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
    padding: 0 14px;
    background: ${p.barBg};
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-bottom: 1px solid ${p.border};
    font-size: 13px;
    color: ${p.text};
  `,
  menubarLeft: css`
    display: flex;
    align-items: center;
    gap: 18px;
  `,
  menubarBrand: css`
    display: flex;
    align-items: center;
    color: ${ACCENT};
  `,
  menubarName: css`
    font-weight: 700;
  `,
  menubarItem: css`
    color: ${p.textSecondary};
    cursor: pointer;
    &:hover {
      color: ${p.hoverText};
    }
  `,
  menubarRight: css`
    display: flex;
    align-items: center;
    gap: 16px;
    color: ${p.textSecondary};
  `,
  menubarBtn: css`
    display: flex;
    align-items: center;
    background: none;
    border: none;
    color: ${p.textSecondary};
    cursor: pointer;
    padding: 0;
    &:hover {
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
    gap: 8px;
    padding: 8px 12px;
    border-radius: 20px;
    background: ${p.floatBg};
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid ${p.dockBorder};
    box-shadow: ${p.shadowFloat};
    transition:
      transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1),
      opacity 0.24s ease;
  `,
  dockHidden: css`
    transform: translateX(-50%) translateY(140%);
    opacity: 0;
    pointer-events: none;
  `,
  dockItem: css`
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    cursor: pointer;
    transition: transform 0.15s cubic-bezier(0.2, 0.8, 0.2, 1);
    transform-origin: bottom center;
    &:hover {
      transform: scale(1.35) translateY(-6px);
    }
  `,
  dockIcon: css`
    width: 46px;
    height: 46px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  `,
  dockDot: css`
    position: absolute;
    bottom: -6px;
    left: 50%;
    transform: translateX(-50%);
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: ${p.textStrong};
  `,
  dockTooltip: css`
    position: absolute;
    bottom: 62px;
    left: 50%;
    transform: translateX(-50%);
    padding: 4px 10px;
    border-radius: 8px;
    background: ${p.tooltipBg};
    border: 1px solid ${p.borderStrong};
    color: ${p.text};
    font-size: 12px;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease;
  `,
  dockDivider: css`
    width: 1px;
    height: 46px;
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
  // ── Menu-bar bell badge ────────────────────────────────────
  bellWrap: css`
    position: relative;
    display: flex;
    align-items: center;
  `,
  bellBadge: css`
    position: absolute;
    top: -7px;
    right: -8px;
    min-width: 15px;
    height: 15px;
    padding: 0 3px;
    border-radius: 8px;
    background: #ef4444;
    color: #fff;
    font-size: 9px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
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
    border-radius: 14px;
    cursor: pointer;
    background: ${p.toastBg};
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowToast};
    transition: transform 0.12s ease;
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
    border-radius: 16px;
    background: ${p.panelBg};
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowPanel};
    overflow: hidden;
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
    background: ${p.faintBg};
    transition: background 0.12s ease;
    &:hover {
      background: ${p.hoverBg};
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
  desktopMenu: css`
    position: absolute;
    z-index: 90;
    min-width: 160px;
    padding: 6px;
    border-radius: 10px;
    background: ${p.panelBg};
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid ${p.border};
    box-shadow: ${p.shadowPanel};
  `,
  desktopMenuItem: css`
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 7px;
    font-size: 13px;
    color: ${p.text};
    cursor: pointer;
    transition: background 0.12s ease;
    &:hover {
      background: ${p.hoverBg};
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
    cursor: pointer;
    span {
      font-size: 12px;
      color: ${p.textSecondary};
      text-align: center;
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
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid ${p.border};
    transform: translateY(0);
    transition:
      transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1),
      opacity 0.24s ease;
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
    transition: background 0.15s ease;
    &:hover {
      background: ${p.hoverBg};
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
    border-radius: 12px;
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
      transform 0.2s ease-in,
      opacity 0.2s ease-in;
    transform-origin: bottom center;
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
