/**
 * Returns a cryptographically secure lowercase hexadecimal string.
 *
 * `crypto.getRandomValues` is available in browsers and WebViews without
 * requiring the page to be a secure context, unlike `crypto.randomUUID`.
 */
export function createSecureRandomHex(byteLength = 16): string {
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}
