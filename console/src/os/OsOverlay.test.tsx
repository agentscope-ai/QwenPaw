import { describe, it, expect } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import OsAppHost from "./OsAppHost";
import { OsModal, OsDrawer } from "./OsOverlay";
import { useOsModal } from "./useOsModal";

function StaticModalProbe() {
  const modal = useOsModal();
  return (
    <>
      {modal.holder}
      <button onClick={() => modal.confirm({ title: "Confirm in window" })}>
        confirm
      </button>
    </>
  );
}

describe("OsOverlay", () => {
  it("portals an open Modal into the window overlay root", () => {
    const { container } = renderWithProviders(
      <OsAppHost>
        <OsModal open title="In-window">
          modal-body
        </OsModal>
      </OsAppHost>,
    );

    const overlayRoot = container.querySelector(".os-window-overlay-root");
    expect(overlayRoot).not.toBeNull();
    const wrap = overlayRoot!.querySelector("[class*='modal-wrap']");
    const mask = overlayRoot!.querySelector("[class*='modal-mask']");
    expect(wrap).not.toBeNull();
    expect(mask).not.toBeNull();
    // Nothing escaped to document.body.
    for (const el of document.querySelectorAll("[class*='modal-wrap']")) {
      expect(overlayRoot!.contains(el)).toBe(true);
    }
  });

  it("portals an open Drawer into the window overlay root, anchored to it", () => {
    const { container } = renderWithProviders(
      <OsAppHost>
        <OsDrawer open title="In-window">
          drawer-body
        </OsDrawer>
      </OsAppHost>,
    );

    const overlayRoot = container.querySelector(".os-window-overlay-root");
    const drawer = overlayRoot!.querySelector(
      "[class*='drawer']",
    ) as HTMLElement | null;
    expect(drawer).not.toBeNull();
    // rootStyle anchors the drawer to the window instead of the viewport.
    const root = overlayRoot!.querySelector(
      "[class*='drawer'][style*='position: absolute']",
    );
    expect(root).not.toBeNull();
  });

  it("keeps default body portals in the classic layout (no provider)", () => {
    renderWithProviders(
      <OsModal open title="Classic">
        modal-body
      </OsModal>,
    );

    const wrap = document.querySelector("[class*='modal-wrap']");
    expect(wrap).not.toBeNull();
    expect(wrap!.closest(".os-window-overlay-root")).toBeNull();
  });

  it("portals hook-based confirm dialogs into the window", async () => {
    const { container, getByRole } = renderWithProviders(
      <OsAppHost>
        <StaticModalProbe />
      </OsAppHost>,
    );

    fireEvent.click(getByRole("button", { name: "confirm" }));

    const overlayRoot = container.querySelector(".os-window-overlay-root");
    await waitFor(() => {
      expect(
        overlayRoot!.querySelector("[class*='modal-wrap']"),
      ).not.toBeNull();
    });
  });
});
