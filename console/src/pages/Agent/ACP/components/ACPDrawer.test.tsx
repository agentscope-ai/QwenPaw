import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Form } from "@agentscope-ai/design";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ACPDrawer } from "./ACPDrawer";
vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { destroy: vi.fn(), error: vi.fn() },
    modal: { confirm },
  }),
}));
vi.mock("@/components/interaction/SettingsDrawer", () => ({
  SettingsDrawer: ({
    children,
    onClose,
  }: {
    children: React.ReactNode;
    onClose: () => void;
  }) => (
    <div role="dialog">
      <button onClick={onClose}>Close editor</button>
      {children}
    </div>
  ),
}));
function Fixture({
  onClose,
  onSubmit,
  isCreateMode = false,
}: {
  onClose: () => void;
  onSubmit: () => Promise<boolean>;
  isCreateMode?: boolean;
}) {
  const [form] = Form.useForm();
  const initialValues = {
    agentKey: "preset",
    command: "node",
    enabled: false,
    trusted: false,
    args: [],
    env: {},
    tool_parse_mode: "call_title" as const,
    stdio_buffer_limit_bytes: 1048576,
  };
  return (
    <ACPDrawer
      open
      activeKey="preset"
      isCreateMode={isCreateMode}
      form={form}
      saving={false}
      onClose={onClose}
      onSubmit={onSubmit}
      initialValues={initialValues}
    />
  );
}
describe("ACP connection editor", () => {
  beforeEach(() => vi.clearAllMocks());
  it("keeps a failed save open and exposes the trusted-execution explanation", async () => {
    const onClose = vi.fn(),
      onSubmit = vi.fn().mockResolvedValue(false);
    render(<Fixture onClose={onClose} onSubmit={onSubmit} />);
    expect(screen.getByText("acp.trustedHelp")).toBeInTheDocument();
    fireEvent.change(document.querySelector("input#command")!, {
      target: { value: "updated-command" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    await act(async () => confirm.mock.calls[0][0].onOk());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("can discard an edit with a missing command", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<Fixture onClose={onClose} onSubmit={onSubmit} />);
    fireEvent.change(document.querySelector("input#command")!, {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    await act(async () => confirm.mock.calls[0][0].onOk());
    expect(onClose).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("closes a new draft without validation or creating a connection", async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<Fixture isCreateMode onClose={onClose} onSubmit={onSubmit} />);
    fireEvent.change(document.querySelector("input#command")!, {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(onSubmit).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
  });
});
