import { renderWithProviders } from "@/test/common_setup";
import { act, cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { adoptAccessSession, clearAccessSession } from "../../api/authSession";
import { getApiToken, setApiAuthMode } from "../../api/config";
import i18n from "../../i18n";
import UnifiedFileCenter from "./UnifiedFileCenter";

vi.mock("./TemporaryAttachmentsPanel", () => ({
  default: () => {
    const [owner] = useState(getApiToken);
    return <div>attachments:{owner}</div>;
  },
}));
vi.mock("./MemoryPanel", () => ({
  default: () => {
    const [owner] = useState(getApiToken);
    return <div>memory:{owner}</div>;
  },
}));
vi.mock("./PersonalLibraryPanel", () => ({
  default: () => <div>library</div>,
}));
vi.mock("./ArtifactPanel", () => ({ default: () => <div>artifact</div> }));
vi.mock("./AgentConfigPanel", () => ({ default: () => <div>config</div> }));
vi.mock("./FilePreviewPane", () => ({
  default: ({ locator }: { locator: { relativePath: string } }) => (
    <div>preview:{locator.relativePath}</div>
  ),
}));

function login(id: string, token = `fixture-${id}`) {
  adoptAccessSession(
    {
      token,
      username: id,
      user: { id, username: id, platform_role: "member", status: "active" },
    },
    false,
  );
}

beforeEach(async () => {
  clearAccessSession(false);
  setApiAuthMode("multi_user");
  login("alice");
  await i18n.changeLanguage("zh");
});

afterEach(() => {
  cleanup();
  clearAccessSession(false);
  setApiAuthMode("legacy");
});

it("removes the former account's memory and does not replay its old locator for the same Agent", async () => {
  renderWithProviders(
    <UnifiedFileCenter
      agentId="same-agent"
      requestContext={{ agentId: "same-agent" }}
      initialLocator={{
        category: "memory",
        agentId: "same-agent",
        relativePath: "alice-private.md",
        memoryScope: "private",
        memorySection: "daily",
      }}
    />,
  );
  expect(screen.getByText("memory:fixture-alice")).toBeVisible();
  act(() => login("bob"));
  expect(screen.queryByText("memory:fixture-alice")).not.toBeInTheDocument();
  expect(screen.getByTestId("unified-file-center")).toHaveAttribute(
    "data-selected-item",
    "",
  );
  await userEvent.setup().click(screen.getByRole("tab", { name: "记忆" }));
  expect(screen.getByText("memory:fixture-bob")).toBeVisible();
});

it("clears an open private preview and cached category panels when the identity changes", () => {
  renderWithProviders(
    <UnifiedFileCenter
      agentId="same-agent"
      requestContext={{ agentId: "same-agent" }}
      initialLocator={{
        category: "artifact",
        agentId: "same-agent",
        relativePath: "alice-report.pdf",
        stableId: "alice-artifact",
      }}
    />,
  );
  expect(screen.getByText("preview:alice-report.pdf")).toBeVisible();
  act(() => login("bob"));
  expect(
    screen.queryByText("preview:alice-report.pdf"),
  ).not.toBeInTheDocument();
  expect(screen.getByText("attachments:fixture-bob")).toBeVisible();
});

it("keeps the current file selection when only the same user's access token is renewed", () => {
  renderWithProviders(
    <UnifiedFileCenter
      agentId="same-agent"
      requestContext={{ agentId: "same-agent" }}
      initialLocator={{
        category: "artifact",
        agentId: "same-agent",
        relativePath: "alice-report.pdf",
        stableId: "alice-artifact",
      }}
    />,
  );
  act(() => login("alice", "fixture-alice-renewed"));
  expect(screen.getByText("preview:alice-report.pdf")).toBeVisible();
  expect(screen.getByTestId("unified-file-center")).toHaveAttribute(
    "data-selected-item",
    "alice-artifact",
  );
});

it("accepts explicit navigation to the new account's file after clearing the former selection", () => {
  const { rerender } = renderWithProviders(
    <UnifiedFileCenter
      agentId="same-agent"
      requestContext={{ agentId: "same-agent" }}
      initialLocator={{
        category: "library",
        agentId: "same-agent",
        relativePath: "alice-contract.md",
        stableId: "alice-document",
      }}
    />,
  );
  act(() => login("bob"));
  expect(
    screen.queryByText("preview:alice-contract.md"),
  ).not.toBeInTheDocument();
  rerender(
    <UnifiedFileCenter
      agentId="same-agent"
      requestContext={{ agentId: "same-agent" }}
      initialLocator={{
        category: "library",
        agentId: "same-agent",
        relativePath: "bob-contract.md",
        stableId: "bob-document",
      }}
    />,
  );
  expect(screen.getByText("preview:bob-contract.md")).toBeVisible();
});
