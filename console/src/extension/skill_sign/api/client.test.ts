import { describe, expect, it, vi, beforeEach } from "vitest";
import { uploadSkillPoolSecureImport } from "./client";

describe("uploadSkillPoolSecureImport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts zip and signature as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        imported: ["demo-skill"],
        count: 1,
        verification: { valid: true, signer: "qwenpaw-skill-sign" },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const zip = new File(["zip-bytes"], "demo-skill.zip", {
      type: "application/zip",
    });
    const sig = new File(["sig-bytes"], "demo-skill.zip.sig", {
      type: "application/octet-stream",
    });

    const result = await uploadSkillPoolSecureImport(zip, sig);
    expect(result.count).toBe(1);
    expect(result.verification?.valid).toBe(true);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const body = init.body as FormData;
    expect(body.get("file")).toBe(zip);
    expect(body.get("signature")).toBe(sig);
  });
});
