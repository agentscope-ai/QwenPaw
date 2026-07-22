/**
 * useOsStyles.ts — Desktop OS PoC styling via antd-style createStyles.
 *
 * Uses the existing antd-style stack (no Tailwind CDN) so the shell stays
 * consistent with the console theme system. Palette: deep neutral gradient
 * wallpaper + glassmorphism panels, single brand-orange accent (#FF7F16).
 */
import { createStyles } from "antd-style";

export const ACCENT = "#FF7F16";
/** Legacy bottom-bar height, kept for existing imports. */
export const TASKBAR_H = 56;
/** macOS-style top menu bar height. */
export const MENUBAR_H = 28;
/** Reserved bottom band for the floating Dock. */
export const DOCK_H = 78;

export const useOsStyles = createStyles(({ css }) => ({
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
    background: rgba(15, 23, 42, 0.86);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(148, 163, 184, 0.14);
    box-shadow:
      0 30px 70px rgba(0, 0, 0, 0.62),
      0 10px 24px rgba(0, 0, 0, 0.42),
      inset 0 1px 0 rgba(255, 255, 255, 0.08);
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
    background: rgba(2, 6, 23, 0.55);
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
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
    color: #e2e8f0;
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
    color: #94a3b8;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
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
    background: rgba(255, 255, 255, 0.02);
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
      border-right: 2px solid rgba(148, 163, 184, 0.6);
      border-bottom: 2px solid rgba(148, 163, 184, 0.6);
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
    background: rgba(2, 6, 23, 0.7);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-top: 1px solid rgba(148, 163, 184, 0.14);
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
      background: rgba(255, 255, 255, 0.1);
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
    color: #cbd5e1;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 13px;
    max-width: 180px;
    transition: all 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #fff;
    }
    span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
  taskItemActive: css`
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
    border-bottom: 2px solid ${ACCENT};
  `,
  tray: css`
    display: flex;
    align-items: center;
    gap: 14px;
    color: #cbd5e1;
    font-size: 12px;
  `,
  clock: css`
    text-align: right;
    line-height: 1.2;
    .date {
      font-size: 10px;
      color: #94a3b8;
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
    background: rgba(15, 23, 42, 0.92);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(148, 163, 184, 0.14);
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
  `,
  launcherSearch: css`
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    margin-bottom: 14px;
    border-radius: 10px;
    background: rgba(2, 6, 23, 0.6);
    border: 1px solid rgba(148, 163, 184, 0.16);
    input {
      flex: 1;
      background: transparent;
      border: none;
      outline: none;
      color: #e2e8f0;
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
      background: rgba(255, 255, 255, 0.06);
    }
    span {
      font-size: 12px;
      color: #cbd5e1;
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
    color: #e2e8f0;
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
      color: #94a3b8;
    }
  `,
  storeToolbar: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
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
    background: rgba(2, 6, 23, 0.45);
    border: 1px solid rgba(148, 163, 184, 0.12);
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
    border: 1px solid rgba(148, 163, 184, 0.24);
    background: transparent;
    color: #e2e8f0;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
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
    color: #94a3b8;
  `,
  storeEmpty: css`
    padding: 14px 24px;
    color: #64748b;
    font-size: 13px;
  `,
  pluginBadge: css`
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    background: rgba(148, 163, 184, 0.16);
    color: #cbd5e1;
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
    color: #cbd5e1;
    background: rgba(148, 163, 184, 0.12);
    border: 1px solid transparent;
    transition: all 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
    }
  `,
  storeChipActive: css`
    background: rgba(255, 127, 22, 0.16);
    border-color: ${ACCENT};
    color: #fff;
  `,
  storeCardDesc: css`
    font-size: 12px;
    color: #94a3b8;
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.4em;
  `,
  storeCardMeta: css`
    font-size: 11px;
    color: #64748b;
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
    background: rgba(2, 6, 23, 0.72);
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
    background: rgba(30, 41, 59, 0.55);
    border: 2px solid transparent;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    cursor: pointer;
    transition: all 0.15s ease;
    &:hover {
      background: rgba(30, 41, 59, 0.8);
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
      color: #94a3b8;
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
    border: 2px dashed rgba(148, 163, 184, 0.3);
    background: transparent;
    color: #94a3b8;
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
    border-top: 1px solid rgba(148, 163, 184, 0.14);
  `,
  mcWindowCard: css`
    height: 130px;
    border-radius: 12px;
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(148, 163, 184, 0.14);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    cursor: pointer;
    transition: all 0.15s ease;
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
    color: #64748b;
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
    background: rgba(2, 6, 23, 0.55);
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
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
    color: #e2e8f0;
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
    background: rgba(2, 6, 23, 0.6);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
    font-size: 13px;
    color: #e2e8f0;
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
    color: #cbd5e1;
    cursor: pointer;
    &:hover {
      color: #fff;
    }
  `,
  menubarRight: css`
    display: flex;
    align-items: center;
    gap: 16px;
    color: #cbd5e1;
  `,
  menubarBtn: css`
    display: flex;
    align-items: center;
    background: none;
    border: none;
    color: #cbd5e1;
    cursor: pointer;
    padding: 0;
    &:hover {
      color: #fff;
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
    background: rgba(30, 41, 59, 0.55);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
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
    background: #e2e8f0;
  `,
  dockTooltip: css`
    position: absolute;
    bottom: 62px;
    left: 50%;
    transform: translateX(-50%);
    padding: 4px 10px;
    border-radius: 8px;
    background: rgba(2, 6, 23, 0.9);
    border: 1px solid rgba(148, 163, 184, 0.2);
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
    background: rgba(255, 255, 255, 0.16);
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
    border: 2px solid rgba(30, 41, 59, 0.9);
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
    background: rgba(30, 41, 59, 0.92);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(148, 163, 184, 0.16);
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5);
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
    background: rgba(255, 255, 255, 0.06);
  `,
  toastBody: css`
    flex: 1;
    min-width: 0;
  `,
  toastTitle: css`
    font-size: 13px;
    font-weight: 600;
    color: #f1f5f9;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  toastText: css`
    font-size: 12px;
    color: #cbd5e1;
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  `,
  toastMeta: css`
    font-size: 10px;
    color: #94a3b8;
    margin-top: 4px;
  `,
  toastClose: css`
    flex: 0 0 auto;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    color: #94a3b8;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    &:hover {
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
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
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 8px;
    background: transparent;
    color: #e2e8f0;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
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
    background: rgba(15, 23, 42, 0.95);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(148, 163, 184, 0.16);
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
    overflow: hidden;
  `,
  ncHeader: css`
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  `,
  ncTitle: css`
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    font-weight: 600;
    color: #f1f5f9;
  `,
  ncIconBtn: css`
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: #94a3b8;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    &:hover {
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
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
    color: #64748b;
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
    background: rgba(255, 255, 255, 0.03);
    transition: background 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
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
    background: rgba(255, 255, 255, 0.06);
  `,
  ncItemBody: css`
    flex: 1;
    min-width: 0;
  `,
  ncItemTitle: css`
    font-size: 13px;
    font-weight: 600;
    color: #e2e8f0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  ncItemText: css`
    font-size: 12px;
    color: #94a3b8;
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  `,
  ncItemTime: css`
    flex: 0 0 auto;
    font-size: 10px;
    color: #64748b;
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
    border-right: 1px solid rgba(148, 163, 184, 0.12);
    background: rgba(2, 6, 23, 0.3);
  `,
  settingsNavItem: css`
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 12px;
    border-radius: 8px;
    cursor: pointer;
    color: #cbd5e1;
    font-size: 13px;
    margin-bottom: 2px;
    transition: background 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.06);
    }
  `,
  settingsNavActive: css`
    background: rgba(255, 127, 22, 0.16);
    color: #fff;
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
    background: rgba(15, 23, 42, 0.95);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(148, 163, 184, 0.16);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.55);
  `,
  desktopMenuItem: css`
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 7px;
    font-size: 13px;
    color: #e2e8f0;
    cursor: pointer;
    transition: background 0.12s ease;
    &:hover {
      background: rgba(255, 255, 255, 0.08);
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
    background: rgba(2, 6, 23, 0.5);
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
    background: rgba(15, 23, 42, 0.96);
    border: 1px solid rgba(148, 163, 184, 0.16);
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
    overflow: hidden;
  `,
  wpHead: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    font-size: 14px;
    font-weight: 600;
    color: #f1f5f9;
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  `,
  wpClose: css`
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: #94a3b8;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    &:hover {
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
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
      color: #cbd5e1;
      text-align: center;
    }
  `,
  wpItemActive: css`
    span {
      color: #fff;
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
    background: rgba(2, 6, 23, 0.72);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(148, 163, 184, 0.16);
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
      background: rgba(255, 255, 255, 0.08);
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
      color: #e2e8f0;
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
  iconsLayer: css`
    position: absolute;
    inset: 0;
    z-index: 0;
  `,
  iconAbsolute: css`
    position: absolute;
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
