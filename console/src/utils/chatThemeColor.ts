const HEX_COLOR_RE = /^#(?:[\da-f]{3,4}|[\da-f]{6}|[\da-f]{8})$/i;
const RGB_COLOR_RE = /^rgba?\(([^)]+)\)$/i;
const HSL_COLOR_RE = /^hsla?\(([^)]+)\)$/i;

function channelToHex(channel: number): string {
  return Math.round(Math.max(0, Math.min(255, channel)))
    .toString(16)
    .padStart(2, "0");
}

function parseChannel(value: string): number | null {
  const normalized = value.trim();
  if (normalized.endsWith("%")) {
    const percent = Number.parseFloat(normalized.slice(0, -1));
    return Number.isFinite(percent) ? (percent / 100) * 255 : null;
  }
  const channel = Number.parseFloat(normalized);
  return Number.isFinite(channel) ? channel : null;
}

function parseRgb(value: string): string | null {
  const match = value.match(RGB_COLOR_RE);
  if (!match) return null;
  const channels = match[1].split(/[\s,]+/).filter(Boolean);
  if (channels.length < 3) return null;
  const parsed = channels.slice(0, 3).map(parseChannel);
  if (parsed.some((channel) => channel === null)) return null;
  return `#${(parsed as number[]).map(channelToHex).join("")}`;
}

function hueToRgb(p: number, q: number, t: number): number {
  let hue = t;
  if (hue < 0) hue += 1;
  if (hue > 1) hue -= 1;
  if (hue < 1 / 6) return p + (q - p) * 6 * hue;
  if (hue < 1 / 2) return q;
  if (hue < 2 / 3) return p + (q - p) * (2 / 3 - hue) * 6;
  return p;
}

function parseHsl(value: string): string | null {
  const match = value.match(HSL_COLOR_RE);
  if (!match) return null;
  const parts = match[1].split(/[\s,]+/).filter(Boolean);
  if (parts.length < 3 || !parts[1].endsWith("%") || !parts[2].endsWith("%")) {
    return null;
  }
  const hue = Number.parseFloat(parts[0]);
  const saturation = Number.parseFloat(parts[1].slice(0, -1)) / 100;
  const lightness = Number.parseFloat(parts[2].slice(0, -1)) / 100;
  if (![hue, saturation, lightness].every(Number.isFinite)) return null;

  const h = (((hue % 360) + 360) % 360) / 360;
  const s = Math.max(0, Math.min(1, saturation));
  const l = Math.max(0, Math.min(1, lightness));
  if (s === 0) {
    const gray = channelToHex(l * 255);
    return `#${gray}${gray}${gray}`;
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return `#${[h + 1 / 3, h, h - 1 / 3]
    .map((channel) => channelToHex(hueToRgb(p, q, channel) * 255))
    .join("")}`;
}

/** Return a six-digit HEX color accepted by the upstream chat theme parser. */
export function toChatThemeHex(
  value: string | undefined,
  fallback: string,
): string {
  if (!value) return fallback;
  const normalized = value.trim();
  if (HEX_COLOR_RE.test(normalized)) {
    const hex = normalized.slice(1);
    if (hex.length === 3 || hex.length === 4) {
      return `#${hex
        .slice(0, 3)
        .split("")
        .map((channel) => `${channel}${channel}`)
        .join("")}`;
    }
    return `#${hex.slice(0, 6)}`;
  }
  return parseRgb(normalized) ?? parseHsl(normalized) ?? fallback;
}
