import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { installMockFetch } from "@/test/mockFetch";

import VideoTemplatePicker from "../VideoTemplatePicker";

function template(overrides: Record<string, unknown>) {
  return {
    templateId: "vlog_daily",
    name: "日常Vlog",
    description: "",
    contentType: "travel",
    scenario: "video_edit",
    colorGrade: "vlog_fresh",
    defaultTransitionKind: "dissolve",
    previewDescription: "",
    iconEmoji: "📷",
    captionBlueprints: [],
    energy: "mid",
    density: "mid",
    decoration: "low",
    source: "builtin",
    ...overrides,
  };
}

const TEMPLATES = [
  template({}),
  template({
    templateId: "custom_1",
    name: "我的风格",
    iconEmoji: "🎨",
    source: "user",
  }),
];

function Harness() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <VideoTemplatePicker
      selectedTemplateId={selected}
      onTemplateSelect={setSelected}
    />
  );
}

describe("VideoTemplatePicker", () => {
  it("walks the style pill lifecycle: default label, card grid, select, reselect default", async () => {
    installMockFetch([
      { match: "/video-templates", response: { json: { items: TEMPLATES } } },
    ]);
    const { container } = render(<Harness />);

    const pill = container.querySelector("[data-style-entry]")!;
    expect(pill).toHaveTextContent("风格: 默认风格");

    await userEvent.click(pill);
    await waitFor(() =>
      expect(document.querySelector("[data-style-popover]")).toBeTruthy(),
    );
    const defaultCard = document.querySelector('[data-style-card="default"]')!;
    expect(defaultCard).toHaveAttribute("data-style-selected");
    const builtinCard = document.querySelector(
      '[data-style-card="vlog_daily"]',
    )!;
    expect(builtinCard.querySelector("img")).toBeTruthy();
    const userCard = document.querySelector('[data-style-card="custom_1"]')!;
    expect(userCard.querySelector("img")).toBeNull();
    expect(userCard).toHaveTextContent("🎨");
    expect(userCard.querySelector("[data-style-card-delete]")).toBeTruthy();

    await userEvent.click(builtinCard);
    await waitFor(() => expect(pill).toHaveTextContent("风格: 日常Vlog"));

    await userEvent.click(pill);
    await waitFor(() =>
      expect(
        document.querySelector('[data-style-card="vlog_daily"]'),
      ).toHaveAttribute("data-style-selected"),
    );
    await userEvent.click(
      document.querySelector('[data-style-card="default"]')!,
    );
    await waitFor(() => expect(pill).toHaveTextContent("风格: 默认风格"));
  });

  it("deletes a user template after confirm and clears its selection", async () => {
    const { calls } = installMockFetch([
      {
        match: "/video-templates/custom_1",
        method: "DELETE",
        response: { json: { deleted: "custom_1" } },
      },
      { match: "/video-templates", response: { json: { items: TEMPLATES } } },
    ]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { container } = render(<Harness />);

    const pill = container.querySelector("[data-style-entry]")!;
    await userEvent.click(pill);
    await waitFor(() =>
      expect(
        document.querySelector('[data-style-card="custom_1"]'),
      ).toBeTruthy(),
    );
    await userEvent.click(
      document.querySelector('[data-style-card="custom_1"]')!,
    );
    await waitFor(() => expect(pill).toHaveTextContent("风格: 我的风格"));

    await userEvent.click(pill);
    await userEvent.click(document.querySelector("[data-style-card-delete]")!);

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "DELETE" &&
            call.url.includes("/video-templates/custom_1"),
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(pill).toHaveTextContent("风格: 默认风格"));
  });
});
