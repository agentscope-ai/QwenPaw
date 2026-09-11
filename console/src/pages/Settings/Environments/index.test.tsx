// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import React from "react";

import { renderWithProviders } from "@/test/common_setup";

const mockApi = vi.hoisted(() => ({
  listEnvs: vi.fn(),
  listEnvCatalog: vi.fn(),
  patchEnvs: vi.fn(),
  deleteEnv: vi.fn(),
  resetEnv: vi.fn(),
}));
const mockMessage = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}));
const mockConfirm = vi.hoisted(() => vi.fn());
vi.mock("../../../api", () => ({ default: mockApi }));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}:${JSON.stringify(options)}` : key,
  }),
}));
vi.mock("@agentscope-ai/design", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@agentscope-ai/design",
  );
  const Modal = ({
    children,
    open,
    onOk,
  }: {
    children?: React.ReactNode;
    open?: boolean;
    onOk?: () => void;
  }) =>
    open ? (
      <div role="dialog">
        {children}
        <button type="button" onClick={onOk}>
          confirm-modal
        </button>
      </div>
    ) : null;
  return {
    ...actual,
    Modal: Object.assign(Modal, {
      confirm: (options: Record<string, unknown>) => mockConfirm(options),
    }),
  };
});

import EnvironmentsPage from "./index";

const timeoutSpec = {
  key: "QWENPAW_LLM_STREAM_IDLE_TIMEOUT",
  default: "30",
  effective_value: "30",
  source: "default" as const,
  description_key:
    "environments.variableDescriptions.QWENPAW_LLM_STREAM_IDLE_TIMEOUT",
  editable: true,
  value_type: "float" as const,
  readonly_reason_code: null,
  mutability: "hot_runtime" as const,
  configured: false,
};

beforeEach(() => {
  mockApi.listEnvs.mockReset().mockResolvedValue([]);
  mockApi.listEnvCatalog.mockReset().mockResolvedValue([timeoutSpec]);
  mockApi.patchEnvs.mockReset().mockResolvedValue([]);
  mockApi.deleteEnv.mockReset().mockResolvedValue([]);
  mockApi.resetEnv.mockReset().mockResolvedValue([]);
  mockMessage.success.mockReset();
  mockMessage.error.mockReset();
  mockMessage.warning.mockReset();
  mockConfirm.mockReset();
});

describe("EnvironmentsPage", () => {
  it("shows known defaults and custom child-process variables", async () => {
    mockApi.listEnvs.mockResolvedValue([
      { key: "QWENPAW_LLM_STREAM_IDLE_TIMEOUT", value: "30" },
      { key: "TAVILY_API_KEY", value: "secret" },
    ]);
    renderWithProviders(<EnvironmentsPage />);

    expect(
      await screen.findByText("QWENPAW_LLM_STREAM_IDLE_TIMEOUT"),
    ).toBeTruthy();
    expect(screen.getByText("TAVILY_API_KEY")).toBeTruthy();
    expect(screen.getByText("environments.source.default")).toBeTruthy();
    const customHeading = screen.getByText("environments.customSettings");
    const liveHeading = screen.getByText("environments.liveSettings");
    const readonlyHeading = screen.getByText("environments.readonlySettings");
    expect(
      customHeading.compareDocumentPosition(liveHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      liveHeading.compareDocumentPosition(readonlyHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("adds one custom variable with incremental PATCH", async () => {
    renderWithProviders(<EnvironmentsPage />);
    await screen.findByText("QWENPAW_LLM_STREAM_IDLE_TIMEOUT");

    fireEvent.click(screen.getByText("environments.addVariable"));
    fireEvent.change(screen.getByPlaceholderText("VARIABLE_NAME"), {
      target: { value: "MY_MCP_TOKEN" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("environments.valuePlaceholder"),
      { target: { value: "new-value" } },
    );
    fireEvent.click(screen.getByText("confirm-modal"));

    await waitFor(() =>
      expect(mockApi.patchEnvs).toHaveBeenCalledWith({
        MY_MCP_TOKEN: "new-value",
      }),
    );
    expect(mockMessage.success).toHaveBeenCalled();
    expect(mockApi.listEnvCatalog).toHaveBeenCalledTimes(2);
  });

  it("renders startup values as locked", async () => {
    mockApi.listEnvCatalog.mockResolvedValue([
      {
        ...timeoutSpec,
        key: "QWENPAW_WORKING_DIR",
        editable: false,
        mutability: "startup_only",
        readonly_reason_code: "startup",
      },
    ]);
    renderWithProviders(<EnvironmentsPage />);

    await screen.findByText("QWENPAW_WORKING_DIR");
    expect(screen.getByText("environments.startupOnly")).toBeTruthy();
    expect(screen.queryByLabelText("common.edit")).toBeNull();
  });

  it("resets a user-configured known value through the reset API", async () => {
    mockApi.listEnvCatalog.mockResolvedValue([
      { ...timeoutSpec, source: "user", configured: true },
    ]);
    renderWithProviders(<EnvironmentsPage />);
    await screen.findByText("QWENPAW_LLM_STREAM_IDLE_TIMEOUT");

    fireEvent.click(screen.getByLabelText("common.reset"));
    const options = mockConfirm.mock.calls[0][0];
    await options.onOk();

    expect(mockApi.resetEnv).toHaveBeenCalledWith(
      "QWENPAW_LLM_STREAM_IDLE_TIMEOUT",
    );
    expect(mockApi.deleteEnv).not.toHaveBeenCalled();
  });
});
