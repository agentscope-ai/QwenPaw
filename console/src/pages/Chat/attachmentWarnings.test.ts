import { describe, expect, it } from "vitest";

import { getAttachmentWarningKey } from "./attachmentWarnings";

describe("getAttachmentWarningKey", () => {
  it("does not warn when multimodal support is unavailable", () => {
    expect(
      getAttachmentWarningKey(
        {
          supportsMultimodal: false,
          supportsImage: false,
          supportsVideo: false,
        },
        "text/plain",
      ),
    ).toBeNull();
  });

  it("warns when an image-only model receives a non-image file", () => {
    expect(
      getAttachmentWarningKey(
        {
          supportsMultimodal: true,
          supportsImage: true,
          supportsVideo: false,
        },
        "video/mp4",
      ),
    ).toBe("chat.attachments.imageOnlyWarning");
  });

  it("does not warn when an image-only model receives an image", () => {
    expect(
      getAttachmentWarningKey(
        {
          supportsMultimodal: true,
          supportsImage: true,
          supportsVideo: false,
        },
        "image/png",
      ),
    ).toBeNull();
  });

  it("does not warn when the model supports video", () => {
    expect(
      getAttachmentWarningKey(
        {
          supportsMultimodal: true,
          supportsImage: true,
          supportsVideo: true,
        },
        "video/mp4",
      ),
    ).toBeNull();
  });
});
