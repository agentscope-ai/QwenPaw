export type AssetReferenceKind = "character" | "scene" | "prop" | "material";

export const assetReferenceValue = (
  kind: AssetReferenceKind,
  assetId: string,
  imageIndex = 0,
) => `asset-ref://${kind}/${assetId}/${imageIndex}`;
