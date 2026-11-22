import { afterEach, describe, expect, it, vi } from "vitest";
import { getConsoleAssetUrl, getRuntimeBasePath } from "./runtimeBasePath";

const originalUrl = location.href;
let baseElement: HTMLBaseElement | undefined;

function setBase(href: string, parent = document.head) {
  baseElement = document.createElement("base");
  baseElement.setAttribute("href", href);
  parent.append(baseElement);
}

describe("runtime base path", () => {
  afterEach(() => {
    baseElement?.remove();
    history.replaceState(null, "", originalUrl);
    vi.unstubAllEnvs();
  });

  it("does not infer the deployment prefix from a deep link", () => {
    vi.stubEnv("BASE_URL", "./");
    history.replaceState(null, "", "/settings/models/providers?tab=local");
    expect(getRuntimeBasePath()).toBe("");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe("/logo-light.svg");
  });

  it("ignores a base outside the document head", () => {
    setBase("/body-only/", document.body);
    expect(getRuntimeBasePath()).toBe("");
  });

  it("keeps public asset paths absolute for an explicit Vite build base", () => {
    vi.stubEnv("BASE_URL", "/site/console/");
    setBase("/");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe(
      "/site/console/logo-light.svg",
    );
  });

  it("uses the server-injected base for public assets on a deep route", () => {
    history.replaceState(null, "", "/app/qwenpaw/web/settings/models");
    setBase("/app/qwenpaw/web/");
    expect(getRuntimeBasePath()).toBe("/app/qwenpaw/web");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe(
      "/app/qwenpaw/web/logo-light.svg",
    );
  });

  it("preserves the raw decoded Unicode and spaces in a base path", () => {
    setBase("/app/中文 console/");
    expect(getRuntimeBasePath()).toBe("/app/中文 console");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe(
      "/app/中文 console/logo-light.svg",
    );
  });

  it.each([
    "./console/",
    "https://foreign.example/",
    "//foreign.example/",
    "/\t/foreign.example/",
    "/app/../admin/",
    "/app/console",
    "/app/console//",
    "/app//admin/",
    "/app\\admin/",
    "/app/?x=1",
    "/app/#section",
    "/app/%71wenpaw/web/",
    "/app/qwenpaw%20web/",
    "/app/%2571wenpaw/web/",
    "/app/%2e%2e/admin/",
  ])("rejects invalid raw bases before URL normalization: %j", (value) => {
    setBase(value);
    expect(getRuntimeBasePath()).toBe("");
  });
});
