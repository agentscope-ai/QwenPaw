import { useState } from "react";
import { Dropdown } from "antd";
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

function Harness({ onAction }: { onAction: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <div onPointerDown={() => setOpen(false)}>
      {open && (
        <Dropdown
          open
          trigger={[]}
          menu={{
            items: [{ key: "action", label: "Arrange", onClick: onAction }],
          }}
          popupRender={(menu) => (
            <div onPointerDown={(event) => event.stopPropagation()}>{menu}</div>
          )}
        >
          <span>anchor</span>
        </Dropdown>
      )}
    </div>
  );
}

describe("Desktop context menu", () => {
  it("runs portal menu actions before the desktop closes the menu", () => {
    const onAction = vi.fn();
    renderWithProviders(<Harness onAction={onAction} />);

    fireEvent.pointerDown(screen.getByText("Arrange"));
    fireEvent.click(screen.getByText("Arrange"));

    expect(onAction).toHaveBeenCalledOnce();
  });
});
