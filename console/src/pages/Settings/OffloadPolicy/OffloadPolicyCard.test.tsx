import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OffloadPolicyCard } from "./OffloadPolicyCard";

const getOffloadPolicy = vi.fn();
const setOffloadPolicy = vi.fn();

vi.mock("../../../api/modules/toolCalls", () => ({
  toolCallsApi: {
    getOffloadPolicy: (...args: unknown[]) => getOffloadPolicy(...args),
    setOffloadPolicy: (...args: unknown[]) => setOffloadPolicy(...args),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback: string) => fallback,
  }),
}));

describe("OffloadPolicyCard", () => {
  beforeEach(() => {
    getOffloadPolicy.mockReset();
    setOffloadPolicy.mockReset();
    getOffloadPolicy.mockResolvedValue({ default_action: "keep_foreground" });
    setOffloadPolicy.mockResolvedValue({ default_action: "offload" });
  });

  it("loads the readable global policy and saves one admin change once", async () => {
    render(<OffloadPolicyCard />);

    const keepForeground = await screen.findByRole("radio", {
      name: /Keep Foreground/,
    });
    expect(keepForeground).toBeChecked();

    fireEvent.click(
      screen.getByRole("radio", { name: /Auto Offload to Background/ }),
    );

    await waitFor(() => {
      expect(setOffloadPolicy).toHaveBeenCalledTimes(1);
      expect(setOffloadPolicy).toHaveBeenCalledWith("offload");
    });
  });

  it("does not write when the selected policy is clicked again", async () => {
    render(<OffloadPolicyCard />);

    fireEvent.click(
      await screen.findByRole("radio", { name: /Keep Foreground/ }),
    );

    expect(setOffloadPolicy).not.toHaveBeenCalled();
  });
});
