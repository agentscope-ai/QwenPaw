import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_key: string, fallback: string) => fallback }),
}));

vi.mock("../../plugins/registry/useChatExtensions", () => ({
  useChatScalarSnapshot: () => ({}),
  useChatListSnapshot: () => ({
    "request.prepend": [],
    "request.append": [],
    "response.prepend": [],
    "response.append": [],
  }),
}));

import { HostResponseCard } from "./HostBubbles";

describe("HostResponseCard", () => {
  it("does not mount deferred content until the user expands it", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <HostResponseCard
        data={
          {
            output: [{ content: [{ type: "text", text: "large" }] }],
            qwenpaw_deferred_render: true,
          } as any
        }
      />,
    );

    expect(screen.queryByTestId("chat-card-mock")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Show large response" }),
    );

    expect(screen.getByTestId("chat-card-mock")).toBeInTheDocument();
  });

  it("hides content immediately when a live card becomes deferred", () => {
    const data = {
      output: [{ content: [{ type: "text", text: "large" }] }],
    } as any;
    const { rerender } = renderWithProviders(
      <HostResponseCard data={data} />,
    );
    expect(screen.getByTestId("chat-card-mock")).toBeInTheDocument();

    rerender(
      <HostResponseCard
        data={{ ...data, qwenpaw_deferred_render: true } as any}
      />,
    );

    expect(screen.queryByTestId("chat-card-mock")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show large response" }),
    ).toBeInTheDocument();
  });
});
