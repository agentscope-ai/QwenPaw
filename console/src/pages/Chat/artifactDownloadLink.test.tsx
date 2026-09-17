import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  artifactIdFromDownloadUrl,
  handleArtifactDownloadLink,
} from "./artifactDownloadLink";

const download = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("../../api/modules/artifacts", () => ({ artifactsApi: { download } }));
beforeEach(() => download.mockClear());

it("downloads a chat artifact link without navigating to an unauthenticated API page", async () => {
  let prevented = false;
  render(<div onClickCapture={event => { handleArtifactDownloadLink(event); prevented = event.defaultPrevented; }}>
    <a href="/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download">下载文档</a>
  </div>);
  fireEvent.click(screen.getByText("下载文档"));
  await waitFor(() => expect(download).toHaveBeenCalledWith("bd20d801-5fa2-4dd0-8d5e-691806601b5b", "artifact"));
  expect(prevented).toBe(true);
});

it("does not send authenticated downloads to an external lookalike URL", () => {
  const event = {target: document.createElement("a"), preventDefault: vi.fn(), stopPropagation: vi.fn()};
  event.target.href = "https://external.example/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download";
  expect(handleArtifactDownloadLink(event)).toBe(false);
  expect(download).not.toHaveBeenCalled();
  expect(event.preventDefault).not.toHaveBeenCalled();
});

it("shares the same strict artifact URL parser with file-center links", () => {
  expect(
    artifactIdFromDownloadUrl(
      "/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download",
    ),
  ).toBe("bd20d801-5fa2-4dd0-8d5e-691806601b5b");
  expect(
    artifactIdFromDownloadUrl(
      "https://external.example/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download",
    ),
  ).toBeNull();
});
