export interface RefSearchItem {
  ref: string;
  name: string;
  type: "element" | "timeline" | "asset" | "artifact" | "visual";
  version?: string;
  thumbnailUrl?: string;
  url?: string;
  createdAt?: string;
  uiLocator: Record<string, string>;
}

export interface ResolvedRef extends RefSearchItem {
  mediaType?: string;
  checksum?: string;
  logicalAssetId?: string;
  assetVersionId?: string;
  slotId?: string;
  artifactVersionId?: string;
}
