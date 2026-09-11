import { describe, it, expect } from "vitest";
import { Drawer, Modal, Select } from "antd";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import OsAppHost from "./OsAppHost";
import { useOverlayContainer } from "./osWindowContainer";

/** Exposes the overlay container the way in-window Modal/Drawer would use it. */
function OverlayProbe() {
  const container = useOverlayContainer();
  return <div data-testid="probe" data-has-container={Boolean(container)} />;
}

describe("OsAppHost", () => {
  it("renders app popups inside the window overlay root, not document.body", () => {
    const { container, getByRole } = renderWithProviders(
      <OsAppHost>
        <Select options={[{ value: "a", label: "Alpha" }]} placeholder="pick" />
      </OsAppHost>,
    );

    // Open the select after mount so the overlay root ref is committed.
    fireEvent.mouseDown(getByRole("combobox"));

    const overlayRoot = container.querySelector(".os-window-overlay-root");
    expect(overlayRoot).not.toBeNull();
    const dropdowns = document.querySelectorAll("[class*='select-dropdown']");
    expect(dropdowns.length).toBeGreaterThan(0);
    // Every popup lives inside the window's overlay root — none portal to
    // document.body (which would cover the whole desktop).
    for (const el of dropdowns) {
      expect(overlayRoot!.contains(el)).toBe(true);
    }
  });

  it("provides the overlay root to useOverlayContainer consumers", () => {
    const { getByTestId } = renderWithProviders(
      <OsAppHost>
        <OverlayProbe />
      </OsAppHost>,
    );
    expect(getByTestId("probe").dataset.hasContainer).toBe("true");
  });

  it("keeps ordinary Modal and Drawer portals inside the window", () => {
    const { container } = renderWithProviders(
      <OsAppHost>
        <Modal open title="Modal title">
          modal body
        </Modal>
        <Drawer open title="Drawer title">
          drawer body
        </Drawer>
      </OsAppHost>,
    );

    const overlayRoot = container.querySelector(".os-window-overlay-root");
    expect(overlayRoot).not.toBeNull();
    expect(overlayRoot!.querySelector("[class*='modal-wrap']")).not.toBeNull();
    expect(overlayRoot!.querySelector("[class*='drawer']")).not.toBeNull();
  });
});
