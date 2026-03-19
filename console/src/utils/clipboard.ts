/**
 * Copy text to clipboard with fallback support for non-secure contexts
 *
 * Uses modern Clipboard API when available in secure context,
 * falls back to document.execCommand('copy') for older browsers or
 * non-HTTPS environments.
 *
 * @param text - The text to copy to clipboard
 * @throws Error if copy operation fails
 */
export async function copyText(text: string): Promise<void> {
  // Modern Clipboard API (requires secure context)
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  // Fallback for non-secure contexts or older browsers
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", ""); // Prevent mobile keyboard
  textarea.style.position = "fixed";
  textarea.style.left = "-999999px";
  textarea.style.top = "-999999px";
  document.body.appendChild(textarea);

  let copied = false;
  try {
    textarea.focus();
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
  }

  if (!copied) {
    throw new Error("Failed to copy text");
  }
}
