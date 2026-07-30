export interface AttachmentCapabilities {
  supportsMultimodal: boolean;
  supportsImage: boolean;
  supportsVideo: boolean;
}

export type AttachmentWarningKey = "chat.attachments.imageOnlyWarning" | null;

export function getAttachmentWarningKey(
  capabilities: AttachmentCapabilities,
  mimeType: string,
): AttachmentWarningKey {
  if (!capabilities.supportsMultimodal) {
    return null;
  }

  if (
    capabilities.supportsImage &&
    !capabilities.supportsVideo &&
    !mimeType.startsWith("image/")
  ) {
    return "chat.attachments.imageOnlyWarning";
  }

  return null;
}
