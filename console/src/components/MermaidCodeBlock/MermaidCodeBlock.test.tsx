import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../contexts/ThemeContext";
import { MermaidCodeBlock } from "./MermaidCodeBlock";

const mermaidMocks = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn().mockResolvedValue({ svg: "<svg>diagram</svg>" }),
}));

vi.mock("mermaid", () => ({
  default: mermaidMocks,
}));

describe("MermaidCodeBlock", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark-mode");
    mermaidMocks.initialize.mockClear();
    mermaidMocks.render.mockClear();
  });

  it("uses readable QwenPaw colors for light and dark themes", async () => {
    localStorage.setItem("qwenpaw-theme", "light");
    const light = render(
      <ThemeProvider>
        <MermaidCodeBlock chart="graph TD; A-->B" />
      </ThemeProvider>,
    );

    await waitFor(() => expect(mermaidMocks.initialize).toHaveBeenCalled());
    expect(mermaidMocks.initialize).toHaveBeenLastCalledWith(
      expect.objectContaining({
        theme: "base",
        themeVariables: expect.objectContaining({
          primaryColor: "#fff7f0",
          primaryTextColor: "#3b2416",
        }),
      }),
    );
    light.unmount();

    localStorage.setItem("qwenpaw-theme", "dark");
    render(
      <ThemeProvider>
        <MermaidCodeBlock chart="graph TD; A-->B" />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(mermaidMocks.initialize).toHaveBeenLastCalledWith(
        expect.objectContaining({
          theme: "base",
          themeVariables: expect.objectContaining({
            lineColor: "#d19a78",
            primaryColor: "#2b211c",
            primaryTextColor: "#fff4ec",
          }),
        }),
      ),
    );
  });
});
