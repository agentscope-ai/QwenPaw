/**
 * Tests for ApprovalContext.
 *
 * Covers:
 * - ApprovalProvider renders children
 * - useApprovalContext returns context with empty approvals by default
 * - setApprovals updates the approvals list
 * - useApprovalContext throws when used outside provider
 */
import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { ReactNode } from "react";
import { ApprovalProvider, useApprovalContext } from "./ApprovalContext";

// Mock the API module that PendingApproval depends on
vi.mock("../api/modules/console", () => ({
  PendingApproval: undefined,
}));

function wrapper({ children }: { children: ReactNode }) {
  return <ApprovalProvider>{children}</ApprovalProvider>;
}

describe("ApprovalProvider + useApprovalContext", () => {
  it("provides empty approvals by default", () => {
    const { result } = renderHook(() => useApprovalContext(), { wrapper });
    expect(result.current.approvals).toEqual([]);
  });

  it("setApprovals updates the approvals list", () => {
    const { result } = renderHook(() => useApprovalContext(), { wrapper });

    const mockApprovals = [
      { id: "1", type: "tool_call", status: "pending" },
    ] as any;

    act(() => {
      result.current.setApprovals(mockApprovals);
    });

    expect(result.current.approvals).toEqual(mockApprovals);
  });

  it("setApprovals can clear approvals", () => {
    const { result } = renderHook(() => useApprovalContext(), { wrapper });

    act(() => {
      result.current.setApprovals([{ id: "1" }] as any);
    });
    act(() => {
      result.current.setApprovals([]);
    });

    expect(result.current.approvals).toEqual([]);
  });

  it("throws when used outside ApprovalProvider", () => {
    // Suppress console.error for expected error
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => {
      renderHook(() => useApprovalContext());
    }).toThrow("useApprovalContext must be used within ApprovalProvider");
    spy.mockRestore();
  });
});
