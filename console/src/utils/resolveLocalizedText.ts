/**
 * Resolve a plain string or locale→string map against the UI language.
 *
 * Priority: exact locale → short code → prefix match (zh ↔ zh-CN) →
 * English → Chinese → first non-empty value.
 * Matches ChannelDrawer.resolveLocalized behavior.
 */
export function resolveLocalizedText(value: unknown, lang: string): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value !== "object") return String(value);

  const dict = value as Record<string, string>;
  const locale = lang || "en";
  const short = locale.split("-")[0].toLowerCase();
  const prefixKey = Object.keys(dict).find(
    (k) => k.split("-")[0].toLowerCase() === short && !!dict[k],
  );

  const exactMatch = dict[locale];
  const shortMatch = dict[short];
  const prefixMatch = prefixKey ? dict[prefixKey] : undefined;
  const englishFallback = dict["en-US"] || dict["en"];
  const chineseFallback = dict["zh-CN"] || dict["zh"];
  const anyNonEmpty = Object.values(dict).find((v) => !!v);

  return (
    exactMatch ||
    shortMatch ||
    prefixMatch ||
    englishFallback ||
    chineseFallback ||
    anyNonEmpty ||
    ""
  );
}
