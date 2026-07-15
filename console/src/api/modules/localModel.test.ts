/**
 * Tests for api/modules/localModel.ts
 *
 * Contract-guard style: verify return pass-through for the local-model
 * lifecycle (server status, download progress, model list, delete,
 * start/stop).  We do not assert exact URLs/bodies (#5438); instead we
 * verify that each method forwards a call to `request` and returns
 * whatever the backend sent — that is the UI's actual contract.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { localModelApi } from "./localModel";
import { request } from "../request";

describe("localModelApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getLocalServerStatus returns LocalServerStatus", async () => {
    const status = { running: false, port: null, model_name: null } as unknown;
    vi.mocked(request).mockResolvedValue(status);
    expect(await localModelApi.getLocalServerStatus()).toBe(status);
  });

  it("getLocalServerUpdateStatus returns the update status object", async () => {
    const status = { update_available: false, latest_version: null } as unknown;
    vi.mocked(request).mockResolvedValue(status);
    expect(await localModelApi.getLocalServerUpdateStatus()).toBe(status);
  });

  it("startLlamacppDownload returns a LocalActionResponse", async () => {
    const resp = { started: true } as unknown;
    vi.mocked(request).mockResolvedValue(resp);
    expect(await localModelApi.startLlamacppDownload()).toBe(resp);
  });

  it("getLlamacppDownloadProgress returns progress info", async () => {
    const progress = {
      downloading: true,
      percent: 0.5,
      downloaded_bytes: 1024,
      total_bytes: 2048,
    } as unknown;
    vi.mocked(request).mockResolvedValue(progress);
    expect(await localModelApi.getLlamacppDownloadProgress()).toBe(progress);
  });

  it("cancelLlamacppDownload returns a LocalActionResponse", async () => {
    const resp = { cancelled: true } as unknown;
    vi.mocked(request).mockResolvedValue(resp);
    expect(await localModelApi.cancelLlamacppDownload()).toBe(resp);
  });

  it("listRecommendedLocalModels resolves to LocalModelInfo[]", async () => {
    const models = [
      { id: "qwen-2.5:1.5b", name: "Qwen 2.5 1.5B", size_mb: 1024 },
    ] as unknown;
    vi.mocked(request).mockResolvedValue(models);
    expect(await localModelApi.listRecommendedLocalModels()).toBe(models);
  });

  it("startLocalModelDownload forwards model name + source and returns LocalActionResponse", async () => {
    const resp = { started: true } as unknown;
    vi.mocked(request).mockResolvedValue(resp);
    const r = await localModelApi.startLocalModelDownload(
      "qwen:1.5b",
      "huggingface",
    );
    expect(r).toBe(resp);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("getLocalModelDownloadProgress returns progress info", async () => {
    const progress = {
      downloading: false,
      percent: 1,
      downloaded_bytes: 0,
      total_bytes: 0,
    } as unknown;
    vi.mocked(request).mockResolvedValue(progress);
    expect(await localModelApi.getLocalModelDownloadProgress()).toBe(progress);
  });

  it("cancelLocalModelDownload returns a LocalActionResponse", async () => {
    const resp = { cancelled: true } as unknown;
    vi.mocked(request).mockResolvedValue(resp);
    expect(await localModelApi.cancelLocalModelDownload()).toBe(resp);
  });

  it("deleteLocalModel encodes the model id and returns a LocalActionResponse", async () => {
    const resp = { deleted: true } as unknown;
    vi.mocked(request).mockResolvedValue(resp);
    const r = await localModelApi.deleteLocalModel("namespace/model");
    expect(r).toBe(resp);
    const arg = vi.mocked(request).mock.calls[0][0] as string;
    expect(arg).toContain("namespace%2Fmodel");
  });

  it("startLocalServer returns { port, model_name }", async () => {
    vi.mocked(request).mockResolvedValue({
      port: 8080,
      model_name: "qwen:1.5b",
    });
    await expect(
      localModelApi.startLocalServer({
        model_name: "qwen:1.5b",
        port: 8080,
      } as never),
    ).resolves.toEqual({ port: 8080, model_name: "qwen:1.5b" });
  });

  it("stopLocalServer returns a LocalActionResponse", async () => {
    vi.mocked(request).mockResolvedValue({ stopped: true });
    await expect(localModelApi.stopLocalServer()).resolves.toEqual({
      stopped: true,
    });
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("disk full"));
    await expect(localModelApi.startLocalServer({} as never)).rejects.toThrow(
      "disk full",
    );
  });
});
