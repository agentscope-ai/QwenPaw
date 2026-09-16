import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { useCodingModeStore } from "@/stores/codingModeStore";
import { projectDirectoryApi } from "@/api/modules/projectDirectory";
import { codingModeApi } from "@/api/modules/codingMode";
import { planApi } from "@/api/modules/plan";
import { ReactAgentCard } from "./ReactAgentCard";
import { Form } from "antd";

const messageError = vi.fn();

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../../../hooks/useTimezoneOptions", () => ({
  useTimezoneOptions: () => [{ value: "UTC", label: "UTC" }],
}));

vi.mock("../../../../components/ProjectSelectModal", () => ({
  default: () => null,
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: messageError } }),
}));

describe("ReactAgentCard governance targeting", () => {
  const context = {
    agentId: "governed-agent",
    governance: true,
  };

  beforeEach(() => {
    messageError.mockReset();
    useAgentStore.setState({ selectedAgent: "sidebar-agent" });
    vi.spyOn(projectDirectoryApi, "get").mockResolvedValue({
      path: "/governed",
      name: "governed",
      is_workspace_default: false,
    });
    vi.spyOn(codingModeApi, "get").mockResolvedValue({
      enabled: false,
      agent_id: "governed-agent",
    });
    vi.spyOn(codingModeApi, "toggle").mockResolvedValue({
      enabled: true,
      agent_id: "governed-agent",
    });
    vi.spyOn(planApi, "getPlanConfig").mockResolvedValue({
      enabled: false,
      auto_enabled: true,
      auto_execute: false,
      complexity_threshold: "medium",
    });
    vi.spyOn(planApi, "updatePlanConfig").mockResolvedValue({
      enabled: true,
      auto_enabled: true,
      auto_execute: false,
      complexity_threshold: "medium",
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useAgentStore.setState({ selectedAgent: "default" });
  });

  const renderCard = () =>
    renderWithProviders(
      <Form>
        <ReactAgentCard
          language="zh"
          savingLang={false}
          onLanguageChange={vi.fn()}
          timezone="UTC"
          savingTimezone={false}
          onTimezoneChange={vi.fn()}
          requestContext={context}
        />
      </Form>,
    );

  it("loads independent settings from the governed agent instead of the sidebar agent", async () => {
    renderCard();

    await waitFor(() => {
      expect(projectDirectoryApi.get).toHaveBeenCalledWith(context);
      expect(codingModeApi.get).toHaveBeenCalledWith(context);
      expect(planApi.getPlanConfig).toHaveBeenCalledWith(context);
    });
  });

  it("writes coding and plan changes to the same governed agent", async () => {
    renderCard();

    fireEvent.click(
      await screen.findByRole("switch", {
        name: "agentConfig.enhancedCodeCapability",
      }),
    );
    const planSwitch = screen
      .getByText("agentConfig.planMode")
      .closest(".ant-form-item")
      ?.querySelector('[role="switch"]');
    expect(planSwitch).toBeTruthy();
    fireEvent.click(planSwitch as HTMLElement);

    await waitFor(() => {
      expect(codingModeApi.toggle).toHaveBeenCalledWith(true, context);
      expect(planApi.updatePlanConfig).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: true }),
        context,
      );
    });
  });

  it("stores governed coding state under the governed agent instead of the sidebar agent", async () => {
    renderCard();

    await waitFor(() => {
      expect(
        useCodingModeStore.getState().codingModeByAgent["governed-agent"],
      ).toBe(false);
    });
    expect(
      useCodingModeStore.getState().codingModeByAgent["sidebar-agent"],
    ).toBeUndefined();
  });

  it("keeps coding mode unchanged and reports the backend error when saving fails", async () => {
    vi.mocked(codingModeApi.toggle).mockRejectedValueOnce(
      new Error("coding failed"),
    );
    renderCard();
    const codingSwitch = await screen.findByRole("switch", {
      name: "agentConfig.enhancedCodeCapability",
    });

    fireEvent.click(codingSwitch);

    await waitFor(() => expect(messageError).toHaveBeenCalledWith("coding failed"));
    expect(codingSwitch).not.toBeChecked();
  });

  it("rolls plan mode back and reports the backend error when saving fails", async () => {
    vi.mocked(planApi.updatePlanConfig).mockRejectedValueOnce(
      new Error("plan failed"),
    );
    renderCard();
    const planSwitch = screen
      .getByText("agentConfig.planMode")
      .closest(".ant-form-item")
      ?.querySelector('[role="switch"]') as HTMLElement;

    fireEvent.click(planSwitch);

    await waitFor(() => expect(messageError).toHaveBeenCalledWith("plan failed"));
    expect(planSwitch).not.toBeChecked();
  });
});
