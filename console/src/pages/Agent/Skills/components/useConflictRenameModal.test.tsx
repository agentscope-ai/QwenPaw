import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

vi.mock("@agentscope-ai/design", () => ({
  Input: () => null,
  Modal: () => null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { useConflictRenameModal } from "./useConflictRenameModal";

describe("useConflictRenameModal", () => {
  it("cancels the pending resolver and clears its proposal", async () => {
    const { result } = renderHook(() => useConflictRenameModal());
    let pending!: Promise<Record<string, string> | null>;
    act(() => {
      pending = result.current.showConflictRenameModal([
        { key: "old", label: "old", suggested_name: "old-2" },
      ]);
    });
    expect(
      (result.current.conflictRenameModal as ReactElement).props.open,
    ).toBe(true);

    act(() => result.current.cancelConflictRenameModal());

    await expect(pending).resolves.toBeNull();
    expect(
      (result.current.conflictRenameModal as ReactElement).props.open,
    ).toBe(false);
  });
});
