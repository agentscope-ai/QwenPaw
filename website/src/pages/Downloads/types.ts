export type LocalizedText = { "zh-CN": string; "en-US": string };

export interface FileMetadata {
  id: string;
  plugin_id?: string;
  name: LocalizedText;
  description: LocalizedText;
  product: string;
  platform: string;
  version: string;
  filename: string;
  url: string;
  size: string;
  size_bytes: number;
  sha256: string;
  updated_at: string;
  type: string;
  author?: string;
}

export interface PlatformData {
  latest: string;
  versions: string[];
}

export interface DesktopIndex {
  product: string;
  updated_at: string;
  platforms: Record<string, PlatformData>;
  files: Record<string, FileMetadata>;
}

export interface MainIndex {
  version: string;
  updated_at: string;
  products: Record<
    string,
    {
      name: { "zh-CN": string; "en-US": string };
      index_url: string;
    }
  >;
}
