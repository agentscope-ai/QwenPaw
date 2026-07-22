import type {
  ChannelDependencyInstallRequest,
  ChannelDependencyInstallSource,
} from "../../../api/modules/channel";

export function createDependencyInstallRequest(
  source: ChannelDependencyInstallSource,
  customIndexUrl: string,
): ChannelDependencyInstallRequest {
  if (source !== "custom") return { source };

  const value = customIndexUrl.trim();
  const url = new URL(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("invalid custom package source");
  }
  return { source, custom_index_url: value };
}
