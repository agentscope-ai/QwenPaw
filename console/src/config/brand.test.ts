import { describe, expect, it } from "vitest";

import {
  ASSISTANT_NAME,
  DESKTOP_UPDATE_CHECK_ENABLED,
  DOCUMENT_TITLE,
  PRODUCT_NAME,
  PUBLIC_MAINTENANCE_LINKS_ENABLED,
  VERSION_BADGE_ENABLED,
} from "./brand";

describe("external brand configuration", () => {
  it("uses one public product identity and hides upstream maintenance links", () => {
    expect(PRODUCT_NAME).toBe("WeldonAgent");
    expect(DOCUMENT_TITLE).toBe(PRODUCT_NAME);
    expect(ASSISTANT_NAME).toBe(PRODUCT_NAME);
    expect(PUBLIC_MAINTENANCE_LINKS_ENABLED).toBe(false);
    expect(VERSION_BADGE_ENABLED).toBe(false);
    expect(DESKTOP_UPDATE_CHECK_ENABLED).toBe(false);
  });
});
