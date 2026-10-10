import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Form } from "@agentscope-ai/design";
import { describe, expect, it, vi } from "vitest";
import { ACPDrawer } from "./ACPDrawer";
vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/hooks/useAutoSave", () => ({
  useAutoSave: (save: () => Promise<unknown>) => ({
    schedule: vi.fn(),
    flush: async () => (await save()) !== false,
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
}: {
  onClose: () => void;
  onSubmit: () => Promise<boolean>;
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
      form={form}
      saving={false}
      onClose={onClose}
      onSubmit={onSubmit}
      initialValues={initialValues}
    />
  );
}
describe("ACP connection editor", () => {
  it("keeps a failed save open and exposes the trusted-execution explanation", async () => {
    const onClose = vi.fn(),
      onSubmit = vi.fn().mockResolvedValue(false);
    render(<Fixture onClose={onClose} onSubmit={onSubmit} />);
    expect(screen.getByText("acp.trustedHelp")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
  });
});
