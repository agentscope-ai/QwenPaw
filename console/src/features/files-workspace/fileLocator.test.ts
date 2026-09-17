import { describe, expect, it } from "vitest";
import {
  artifactIdFromDownloadUrl,
  buildFileCenterPath,
  parseFileCenterLocation,
  type FileLocator,
} from "./fileLocator";

describe("fileLocator", () => {
  it("round-trips a private daily memory locator", () => {
    const locator: FileLocator = {
      category: "memory",
      agentId: "agent-a",
      relativePath: "2026-09-15/topic.md",
      memoryScope: "private",
      memorySection: "daily",
    };

    expect(parseFileCenterLocation(buildFileCenterPath(locator))).toEqual(
      locator,
    );
  });

  it("rejects an invalid memory scope instead of falling back", () => {
    expect(
      parseFileCenterLocation(
        "/files?agentId=agent-a&category=memory&item=topic.md&memoryScope=user-b&memorySection=daily",
      ),
    ).toBeNull();
  });

  it("rejects parent traversal in a relative path", () => {
    expect(
      parseFileCenterLocation(
        "/files?agentId=agent-a&category=memory&item=../secret.md&memoryScope=private&memorySection=daily",
      ),
    ).toBeNull();
  });

  it("requires a UUID for an artifact stable id", () => {
    expect(
      parseFileCenterLocation(
        "/files?agentId=agent-a&category=artifact&stableId=not-an-id&item=report.pdf",
      ),
    ).toBeNull();
  });

  it("extracts an artifact id only from a same-origin download URL", () => {
    expect(
      artifactIdFromDownloadUrl(
        "/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download",
      ),
    ).toBe("bd20d801-5fa2-4dd0-8d5e-691806601b5b");
    expect(
      artifactIdFromDownloadUrl(
        "https://evil.example/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download",
      ),
    ).toBeNull();
  });
});
