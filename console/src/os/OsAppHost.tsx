/**
 * OsAppHost.tsx — Per-window app environment: content surface + overlay
 * boundary.
 *
 * Two overlay semantics exist in the Desktop OS:
 *
 *   App overlay    — belongs to ONE window (Select/Dropdown/Tooltip popups,
 *                    in-app Modal/Drawer). Hosted here, inside the window.
 *   System overlay — belongs to the desktop (NotificationCenter, Mission
 *                    Control, WallpaperPicker, global message/notification).
 *                    Those keep portaling to document.body / desktop layers.
 *
 * OsAppHost renders a non-scrolling overlay root wrapping the scrollable
 * content, then:
 *   - antd ConfigProvider getPopupContainer → popups render inside the
 *     window automatically (no per-page work; nested ConfigProvider
 *     inherits the app theme).
 *   - OsWindowContainerContext → standard mount point for in-window
 *     Modal/Drawer via useOverlayContainer() + the scoped CSS in
 *     osWindowBody.css (business pages migrate incrementally).
 *   - OsWindowSizeContext → live content width for container-aware hooks.
 */
import { useState } from "react";
import { ConfigProvider } from "antd";
import { OsWindowContainerContext } from "./osWindowContainer";
import { OsWindowSizeContext } from "./osWindowSizeContext";
import { useElementWidth } from "./useElementWidth";

interface OsAppHostProps {
  /** Class for the scrollable content element (styles.content + marker). */
  contentClassName?: string;
  /** Themed-surface overrides for the content element. */
  contentStyle?: React.CSSProperties;
  children: React.ReactNode;
}

export default function OsAppHost({
  contentClassName,
  contentStyle,
  children,
}: OsAppHostProps) {
  // Overlay root: fills the content area but does NOT scroll, so popups
  // and in-window modals stay put while the app content scrolls beneath.
  const [overlayRoot, setOverlayRoot] = useState<HTMLElement | null>(null);
  // Scrollable content element; its width drives container-aware hooks.
  const [contentEl, setContentEl] = useState<HTMLElement | null>(null);
  const contentWidth = useElementWidth(contentEl);

  return (
    <div
      ref={setOverlayRoot}
      className="os-window-overlay-root"
      style={{
        position: "relative",
        flex: 1,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div className={contentClassName} style={contentStyle} ref={setContentEl}>
        <ConfigProvider
          getPopupContainer={(trigger) =>
            overlayRoot ?? trigger?.parentElement ?? document.body
          }
        >
          <OsWindowContainerContext.Provider value={overlayRoot}>
            <OsWindowSizeContext.Provider value={contentWidth}>
              {children}
            </OsWindowSizeContext.Provider>
          </OsWindowContainerContext.Provider>
        </ConfigProvider>
      </div>
    </div>
  );
}
