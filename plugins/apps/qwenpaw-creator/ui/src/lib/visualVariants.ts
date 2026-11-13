import type { VisualVariantDocument } from "@/contracts/creator";

export function visualVariantLabel(
  variant: VisualVariantDocument,
  maxLength = 48,
): string {
  const requirement =
    variant.requirements.split(/\r?\n|[。！？!?]/, 1)[0]?.trim() ?? "";
  const fallback = variant.variant_id.replace(
    /^(?:visual-variant:|variant:|var:)/,
    "",
  );
  const label = requirement || fallback;
  return label.length > maxLength
    ? `${label.slice(0, maxLength).trimEnd()}…`
    : label;
}
