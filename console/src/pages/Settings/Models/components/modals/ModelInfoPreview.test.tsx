import { describe, it, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import api from "../../../../../api";
import { ModelInfoPreview } from "./ModelInfoPreview";
import { expect } from "vitest";

vi.mock("../../../../../api", () => ({
  default: {
    listModelTemplates: vi.fn(),
    previewModelInfo: vi.fn(),
  },
}));

describe("ModelInfoPreview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listModelTemplates).mockResolvedValue([]);
  });
  it("previews an alias using the selected template without changing the ID", async () => {
    vi.mocked(api.previewModelInfo).mockResolvedValue({
      id: "deployment-123",
      name: "Deployment",
      effective_max_input_length: 1000000,
      context_length_source: "template",
      max_output_length: 131072,
      max_output_length_source: "template",
    } as never);
    renderWithProviders(
      <ModelInfoPreview
        providerId="gateway"
        modelId="deployment-123"
        templateId="dashscope/qwen3.8-max"
        onTemplateChange={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(api.previewModelInfo).toHaveBeenCalledWith(
        "gateway",
        "deployment-123",
        "dashscope/qwen3.8-max",
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("1M");
    expect(screen.getByRole("status")).toHaveTextContent("131.1K");
  });
  it("explains metadata lookup failure without preventing manual entry", async () => {
    vi.mocked(api.previewModelInfo).mockRejectedValue(new Error("offline"));
    renderWithProviders(
      <ModelInfoPreview
        providerId="gateway"
        modelId="unknown"
        onTemplateChange={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "models.modelInfoUnavailable",
      ),
    );
  });
});
