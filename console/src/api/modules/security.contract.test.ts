/**
 * Contract tests for the `securityApi` members the existing `security.test.ts`
 * leaves out: deny-paths protection (read + update), `getFileGuard`,
 * `updateSkillScanner`, `getBlockedHistory`, `removeBlockedEntry`, and the
 * allow-no-auth-hosts pair.
 *
 * Division of labour (no overlap with the existing file):
 *   - `security.test.ts` pins tool guard read/update, builtin rules, sandbox
 *     read/update, `updateFileGuard`, `getSkillScanner`, `clearBlockedHistory`,
 *     `addToWhitelist`, `removeFromWhitelist`.
 *   - this file pins everything above that the existing file does not touch.
 *
 * The existing file is left untouched - a second test file for the same module
 * is an established pattern in this repo and removes the risk of clobbering
 * somebody else's lines while appending.
 *
 * Two things worth pinning precisely, because both are easy to break without
 * any test noticing:
 *   1. `removeBlockedEntry` interpolates a number straight into the path, so a
 *      zero index must not be stringified into something falsy-skipping, and the
 *      value is NOT percent-encoded (unlike `removeFromWhitelist`).
 *   2. the GET members call `request` with a single argument - adding an empty
 *      options object would change the wire shape.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { request } from "../request";
import { securityApi } from "./security";
import type {
  AllowNoAuthHostsResponse,
  BlockedSkillRecord,
  DenyPathsProtectionResponse,
  FileGuardResponse,
  SkillScannerConfig,
} from "./security";

vi.mock("../request", () => ({ request: vi.fn() }));

const DENY_PATHS = "/config/security/sandbox/deny-paths-protection";
const FILE_GUARD = "/config/security/file-guard";
const SCANNER = "/config/security/skill-scanner";
const BLOCKED_HISTORY = "/config/security/skill-scanner/blocked-history";
const NO_AUTH_HOSTS = "/config/security/allow-no-auth-hosts";

beforeEach(() => {
  vi.mocked(request).mockReset();
  vi.mocked(request).mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("securityApi - deny paths protection", () => {
  it("getDenyPathsProtection GETs with a single argument", async () => {
    const response: DenyPathsProtectionResponse = {
      active: true,
      protected_paths: ["/etc"],
      failed_paths: [],
      platform_supported: true,
      message: null,
    };
    vi.mocked(request).mockResolvedValue(response);

    await expect(securityApi.getDenyPathsProtection()).resolves.toEqual(
      response,
    );
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(DENY_PATHS);
  });

  it("surfaces a failed deny-paths read instead of defaulting to inactive", async () => {
    vi.mocked(request).mockRejectedValue(new Error("forbidden"));

    await expect(securityApi.getDenyPathsProtection()).rejects.toThrow(
      "forbidden",
    );
  });

  it("updateDenyPathsProtection PUTs the enabled flag", async () => {
    const response: DenyPathsProtectionResponse = {
      active: true,
      protected_paths: ["/etc", "/root/.ssh"],
      failed_paths: [],
      platform_supported: true,
      message: null,
    };
    vi.mocked(request).mockResolvedValue(response);

    await securityApi.updateDenyPathsProtection({ enabled: true });

    expect(request).toHaveBeenCalledWith(DENY_PATHS, {
      method: "PUT",
      body: JSON.stringify({ enabled: true }),
    });
  });

  it("updateDenyPathsProtection serialises enabled false rather than dropping it", async () => {
    vi.mocked(request).mockResolvedValue({});

    await securityApi.updateDenyPathsProtection({ enabled: false });

    const init = vi.mocked(request).mock.calls[0][1] as { body: string };
    expect(init.body).toBe('{"enabled":false}');
  });

  it("reports failed paths verbatim so the UI can show which ones did not apply", async () => {
    const response: DenyPathsProtectionResponse = {
      active: false,
      protected_paths: ["/etc"],
      failed_paths: ["/proc/self"],
      platform_supported: false,
      message: "unsupported platform",
    };
    vi.mocked(request).mockResolvedValue(response);

    await expect(securityApi.getDenyPathsProtection()).resolves.toMatchObject({
      failed_paths: ["/proc/self"],
      message: "unsupported platform",
    });
  });
});

describe("securityApi - file guard", () => {
  it("getFileGuard GETs with a single argument", async () => {
    const response: FileGuardResponse = {
      enabled: true,
      paths: ["/secret"],
      allow_preview_outside_workspace: false,
    };
    vi.mocked(request).mockResolvedValue(response);

    await expect(securityApi.getFileGuard()).resolves.toEqual(response);
    expect(request).toHaveBeenCalledWith(FILE_GUARD);
  });

  it("returns an empty path list untouched", async () => {
    vi.mocked(request).mockResolvedValue({
      enabled: false,
      paths: [],
      allow_preview_outside_workspace: true,
    });

    await expect(securityApi.getFileGuard()).resolves.toEqual({
      enabled: false,
      paths: [],
      allow_preview_outside_workspace: true,
    });
  });

  it("sends a partial update body without filling in defaults", async () => {
    vi.mocked(request).mockResolvedValue({});

    // The update body type makes every field optional; the caller's shape must
    // reach the wire exactly as given.
    await securityApi.updateFileGuard({
      allow_preview_outside_workspace: true,
    });

    expect(request).toHaveBeenCalledWith(FILE_GUARD, {
      method: "PUT",
      body: JSON.stringify({ allow_preview_outside_workspace: true }),
    });
  });

  it("keeps non-ASCII guard paths intact", async () => {
    vi.mocked(request).mockResolvedValue({});

    await securityApi.updateFileGuard({ paths: ["/工作区/密钥"] });

    const init = vi.mocked(request).mock.calls[0][1] as { body: string };
    expect(JSON.parse(init.body)).toEqual({ paths: ["/工作区/密钥"] });
  });
});

describe("securityApi - skill scanner", () => {
  it("updateSkillScanner PUTs the whole config", async () => {
    const config: SkillScannerConfig = {
      mode: "warn",
      timeout: 15,
      whitelist: [],
    };
    vi.mocked(request).mockResolvedValue(config);

    await expect(securityApi.updateSkillScanner(config)).resolves.toEqual(
      config,
    );
    expect(request).toHaveBeenCalledWith(SCANNER, {
      method: "PUT",
      body: JSON.stringify(config),
    });
  });

  it("serialises a zero timeout instead of treating it as absent", async () => {
    vi.mocked(request).mockResolvedValue({});

    await securityApi.updateSkillScanner({
      mode: "off",
      timeout: 0,
      whitelist: [],
    });

    const init = vi.mocked(request).mock.calls[0][1] as { body: string };
    expect(init.body).toContain('"timeout":0');
  });

  it("getBlockedHistory GETs the history collection with a single argument", async () => {
    const records: BlockedSkillRecord[] = [
      {
        skill_name: "shady",
        blocked_at: "2026-09-21T10:00:00+08:00",
        max_severity: "high",
        findings: [
          {
            severity: "high",
            title: "credential access",
            description: "reads ~/.ssh",
            file_path: "install.sh",
            line_number: 12,
            rule_id: "secret-read",
          },
        ],
        content_hash: "abc123",
        action: "blocked",
      },
    ];
    vi.mocked(request).mockResolvedValue(records);

    await expect(securityApi.getBlockedHistory()).resolves.toEqual(records);
    expect(request).toHaveBeenCalledWith(BLOCKED_HISTORY);
  });

  it("resolves an empty blocked history as an empty array", async () => {
    vi.mocked(request).mockResolvedValue([]);

    await expect(securityApi.getBlockedHistory()).resolves.toEqual([]);
  });

  it("removeBlockedEntry DELETEs the entry by numeric index", async () => {
    vi.mocked(request).mockResolvedValue({ removed: true });

    await securityApi.removeBlockedEntry(3);

    expect(request).toHaveBeenCalledWith(`${BLOCKED_HISTORY}/3`, {
      method: "DELETE",
    });
  });

  it("does not skip index zero", async () => {
    vi.mocked(request).mockResolvedValue({ removed: true });

    await securityApi.removeBlockedEntry(0);

    expect(request).toHaveBeenCalledWith(`${BLOCKED_HISTORY}/0`, {
      method: "DELETE",
    });
  });

  it("propagates a failed single-entry removal", async () => {
    vi.mocked(request).mockRejectedValue(new Error("index out of range"));

    await expect(securityApi.removeBlockedEntry(99)).rejects.toThrow(
      "index out of range",
    );
  });
});

describe("securityApi - allow no auth hosts", () => {
  it("getAllowNoAuthHosts GETs with a single argument", async () => {
    const response: AllowNoAuthHostsResponse = { hosts: ["127.0.0.1"] };
    vi.mocked(request).mockResolvedValue(response);

    await expect(securityApi.getAllowNoAuthHosts()).resolves.toEqual(response);
    expect(request).toHaveBeenCalledWith(NO_AUTH_HOSTS);
  });

  it("updateAllowNoAuthHosts PUTs the host list", async () => {
    const response: AllowNoAuthHostsResponse = {
      hosts: ["127.0.0.1", "::1"],
    };
    vi.mocked(request).mockResolvedValue(response);

    await securityApi.updateAllowNoAuthHosts({ hosts: ["127.0.0.1", "::1"] });

    expect(request).toHaveBeenCalledWith(NO_AUTH_HOSTS, {
      method: "PUT",
      body: JSON.stringify({ hosts: ["127.0.0.1", "::1"] }),
    });
  });

  it("serialises clearing the list as an empty array, not as undefined", async () => {
    vi.mocked(request).mockResolvedValue({ hosts: [] });

    await securityApi.updateAllowNoAuthHosts({ hosts: [] });

    const init = vi.mocked(request).mock.calls[0][1] as { body: string };
    expect(init.body).toBe('{"hosts":[]}');
  });

  it("passes unusual host strings through unmodified", async () => {
    vi.mocked(request).mockResolvedValue({ hosts: [] });
    const hosts = ["10.0.0.0/8", "内网主机", "host with space"];

    await securityApi.updateAllowNoAuthHosts({ hosts });

    const init = vi.mocked(request).mock.calls[0][1] as { body: string };
    expect(JSON.parse(init.body)).toEqual({ hosts });
  });

  it("propagates a rejected update", async () => {
    vi.mocked(request).mockRejectedValue(new Error("host not allowed"));

    await expect(
      securityApi.updateAllowNoAuthHosts({ hosts: ["0.0.0.0"] }),
    ).rejects.toThrow("host not allowed");
  });
});
