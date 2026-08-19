/**
 * OsOverlay.tsx — OS-aware Modal / Drawer wrappers (App overlay semantics).
 *
 * These wrappers let callers explicitly opt into the OS host without wiring
 * the window container by hand:
 *
 *   - Inside an OS window: portal into the window's overlay root (from
 *     OsAppHost via useOverlayContainer), positioned against the window by
 *     the scoped rules in osWindowBody.css / an inline rootStyle.
 *   - Classic layout (no provider): plain antd Modal/Drawer on
 *     document.body — behaviour is unchanged.
 *
 * Explicit getContainer/rootStyle props always win over the OS defaults.
 */
import { Modal, Drawer, type ModalProps, type DrawerProps } from "antd";
import { useOverlayContainer } from "./osWindowContainer";

export function OsModal(props: ModalProps) {
  const container = useOverlayContainer();
  if (!container) return <Modal {...props} />;
  return <Modal getContainer={() => container} {...props} />;
}

export function OsDrawer(props: DrawerProps) {
  const container = useOverlayContainer();
  if (!container) return <Drawer {...props} />;
  return (
    <Drawer
      getContainer={() => container}
      // Antd keeps position:fixed even with a custom container; anchor the
      // drawer to the window's overlay root instead of the viewport.
      rootStyle={{ position: "absolute" }}
      {...props}
    />
  );
}
