import { renderWithProviders } from "@/test/common_setup";
import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FilePreviewPane, { fileLocatorDownloadUrl } from "./FilePreviewPane";

afterEach(() => vi.unstubAllGlobals());

it("loads a registered artifact by stable id instead of a workspace path", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response("# hello artifact", {
      status: 200,
      headers: { "Content-Type": "text/markdown" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  renderWithProviders(
    <FilePreviewPane
      locator={{
        category: "artifact",
        agentId: "agent-a",
        stableId: "bd20d801-5fa2-4dd0-8d5e-691806601b5b",
        relativePath: "report.md",
      }}
      requestContext={{ agentId: "agent-a" }}
    />,
  );

  expect(
    await screen.findByRole("heading", { name: "hello artifact" }),
  ).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download",
    expect.objectContaining({ headers: expect.any(Object) }),
  );
});

it("uses the scoped personal-library download endpoint for PDF preview", () => {
  expect(
    fileLocatorDownloadUrl({
      category: "library",
      agentId: "agent-a",
      stableId: "8c742924-3a11-41b2-9cd1-04ec85f8ef95",
      relativePath: "artifacts/report.pdf",
    }),
  ).toBe(
    "/api/console/personal-library/documents/8c742924-3a11-41b2-9cd1-04ec85f8ef95/download",
  );
});
