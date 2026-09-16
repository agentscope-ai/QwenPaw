import { expect, it, vi } from "vitest";
import { artifactsApi } from "./artifacts";
vi.mock("../authHeaders", () => ({buildAuthHeaders: () => ({Authorization:"Bearer test", "X-Agent-Id":"default"})}));
const download = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const fresh = vi.hoisted(() => vi.fn().mockResolvedValue(true));
vi.mock("../authSession", () => ({ensureAccessSessionFresh: fresh}));
vi.mock("../../utils/downloadFileFromUrl", () => ({downloadFileFromUrl: download}));
it("downloads private artifacts with the authenticated agent headers", async () => {
  await artifactsApi.download("artifact-id", "report.md");
  expect(download).toHaveBeenCalledWith("/api/console/artifacts/artifact-id/download", "report.md", expect.objectContaining({headers:{Authorization:"Bearer test", "X-Agent-Id":"default"}}));
});

it("does not download when the expired login session cannot be renewed", async () => {
  download.mockClear();
  fresh.mockResolvedValueOnce(false);
  await expect(artifactsApi.download("artifact-id", "report.md")).rejects.toThrow("Not authenticated");
  expect(download).not.toHaveBeenCalled();
});
