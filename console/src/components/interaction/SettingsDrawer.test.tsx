import { useState } from "react";
import { App, ConfigProvider, Form, Grid, Input } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoSave } from "@/hooks/useAutoSave";
import { SettingsDrawer } from "./SettingsDrawer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function Editor({ onSave }: { onSave: () => Promise<void> }) {
  const [open, setOpen] = useState(true);
  const [form] = Form.useForm();
  const { schedule, requestClose } = useAutoSave(async () => {
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    await onSave();
  });
  return (
    <SettingsDrawer
      open={open}
      title="Configuration"
      onClose={() => void requestClose(() => setOpen(false))}
      destroyOnHidden
    >
      <Form form={form} onValuesChange={schedule}>
        <Form.Item name="token" rules={[{ required: true }]}>
          <Input aria-label="Token" />
        </Form.Item>
        <Form.Item name="proxy">
          <Input aria-label="Proxy" />
        </Form.Item>
      </Form>
    </SettingsDrawer>
  );
}

afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  // jsdom has no pointer capture or scrolling engine used by Vaul.
  Object.defineProperties(HTMLElement.prototype, {
    setPointerCapture: { configurable: true, value: vi.fn() },
    releasePointerCapture: { configurable: true, value: vi.fn() },
    hasPointerCapture: { configurable: true, value: () => false },
  });
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

async function findConfirmation() {
  // rc-dialog uses the same generated title ID for all modals in tests.
  const title = await screen.findByText("common.discardChangesTitle", {
    selector: ".ant-modal-confirm-title",
  });
  return title.closest<HTMLElement>('[role="dialog"]')!;
}

describe("configuration editor dismissal", () => {
  it.each(["button", "backdrop", "escape"])(
    "allows discarding invalid desktop edits using the %s",
    async (action) => {
      vi.spyOn(Grid, "useBreakpoint").mockReturnValue({ md: true });
      const user = userEvent.setup();
      const onSave = vi.fn().mockResolvedValue(undefined);
      render(
        <ConfigProvider theme={{ token: { motion: false } }}>
          <App>
            <Editor onSave={onSave} />
          </App>
        </ConfigProvider>,
      );
      await user.type(screen.getByRole("textbox", { name: "Proxy" }), "draft");
      const editor = screen.getByRole("dialog", { name: "Configuration" });
      if (action === "button") {
        await user.click(within(editor).getByRole("button", { name: "Close" }));
      } else if (action === "backdrop") {
        await user.click(editor.closest(".ant-modal-wrap")!);
      } else {
        fireEvent.keyDown(editor.closest(".ant-modal-wrap")!, {
          key: "Escape",
          keyCode: 27,
        });
      }
      const confirmation = await findConfirmation();
      await user.click(
        within(confirmation).getByRole("button", {
          name: "common.discardAndClose",
        }),
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("dialog", { name: "Configuration" }),
        ).not.toBeInTheDocument(),
      );
      expect(onSave).not.toHaveBeenCalled();
    },
  );

  it("keeps mobile confirmation inside the sheet and allows continuing or discarding", async () => {
    vi.spyOn(Grid, "useBreakpoint").mockReturnValue({ md: false });
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <Editor onSave={onSave} />
        </App>
      </ConfigProvider>,
    );
    await user.type(screen.getByRole("textbox", { name: "Proxy" }), "draft");
    await user.click(screen.getByRole("button", { name: "common.close" }));
    let confirmation = await findConfirmation();
    expect(confirmation.closest("[data-vaul-drawer]")).not.toBeNull();
    await waitFor(() =>
      expect(
        within(confirmation).getByRole("button", {
          name: "common.keepEditing",
        }),
      ).toHaveFocus(),
    );
    await user.click(
      within(confirmation).getByRole("button", { name: "common.keepEditing" }),
    );
    await waitFor(() => expect(confirmation).not.toBeVisible());
    expect(screen.getByRole("textbox", { name: "Proxy" })).toHaveValue("draft");
    await user.click(screen.getByRole("button", { name: "common.close" }));
    confirmation = await findConfirmation();
    await user.click(
      within(confirmation).getByRole("button", {
        name: "common.discardAndClose",
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Configuration" }),
      ).not.toBeInTheDocument(),
    );
    expect(onSave).not.toHaveBeenCalled();
  });
});
