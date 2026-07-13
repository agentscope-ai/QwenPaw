/**
 * LocalPathLinkifier — post-processes rendered chat message DOM to turn
 * detected local file paths into clickable links that open the system
 * file explorer via the Tauri `open_in_explorer` command.
 *
 * Only active inside the Desktop app (guarded by `isDesktopApp()`).
 */
import { useEffect, useRef } from "react";
import { isDesktopApp } from "../../tauri/backendRuntime";
import { findLocalPaths, openInExplorer } from "../../utils/localPathDetector";
// Side-effect import: injects :global CSS for .qwenpaw-local-path-link.
import "./LocalPathLinks.module.less";

/** CSS class applied to injected path-link anchors. */
const LINK_CLASS = "qwenpaw-local-path-link";

/** Data attribute storing the original path on each injected anchor. */
const DATA_PATH_ATTR = "data-local-path";

/** Marker attribute to avoid re-processing the same subtree. */
const PROCESSED_ATTR = "data-qwenpaw-paths";

/**
 * Tags whose text content should NOT be scanned — code blocks (not inline
 * code, which the markdown renderer may wrap paths in), existing links, and
 * form elements must remain untouched.
 *
 * NOTE: `CODE` is intentionally NOT listed here.  Inline `<code>` elements
 * produced by the markdown renderer (e.g. backtick-wrapped paths) SHOULD be
 * linkified.  Only `<pre><code>` blocks are skipped via the `isInsidePreCode`
 * check below.
 */
const SKIP_PARENT_TAGS = new Set([
  "PRE",
  "A",
  "TEXTAREA",
  "INPUT",
  "SCRIPT",
  "STYLE",
]);

/**
 * Walk the subtree rooted at `node`, looking for text nodes that contain
 * local file paths.  Each detected path is wrapped in an `<a>` element.
 *
 * Returns true if any replacement was made (so the caller can mark the
 * subtree as processed).
 */
function linkifyTextNode(root: Node): boolean {
  let didReplace = false;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);

  // Collect candidates first to avoid mutating the tree while walking.
  const candidates: Text[] = [];
  let current: Text | null;
  while ((current = walker.nextNode() as Text | null)) {
    // Skip text nodes inside code blocks / links / etc.
    let parent: HTMLElement | null = current.parentElement;
    let shouldSkip = false;
    while (parent && parent !== root) {
      if (SKIP_PARENT_TAGS.has(parent.tagName)) {
        shouldSkip = true;
        break;
      }
      // Skip <code> only when it is inside a <pre> (i.e. a fenced code block).
      // Inline <code> (backtick-wrapped text in markdown) should still be
      // linkified so that paths rendered as `C:\foo\bar` become clickable.
      if (
        parent.tagName === "CODE" &&
        parent.parentElement?.tagName === "PRE"
      ) {
        shouldSkip = true;
        break;
      }
      // Also skip if already inside one of our injected links.
      if (parent.classList?.contains(LINK_CLASS)) {
        shouldSkip = true;
        break;
      }
      parent = parent.parentElement;
    }
    if (shouldSkip) continue;

    if (current.nodeValue && findLocalPaths(current.nodeValue).length > 0) {
      candidates.push(current);
    }
  }

  for (const textNode of candidates) {
    const text = textNode.nodeValue;
    if (!text) continue;

    const matches = findLocalPaths(text);
    if (matches.length === 0) continue;

    const fragment = document.createDocumentFragment();
    let cursor = 0;

    for (const match of matches) {
      // Text before the match.
      if (match.start > cursor) {
        fragment.appendChild(
          document.createTextNode(text.slice(cursor, match.start)),
        );
      }

      // The link element.
      const anchor = document.createElement("a");
      anchor.className = LINK_CLASS;
      anchor.setAttribute(DATA_PATH_ATTR, match.path);
      anchor.href = "#";
      anchor.textContent = match.path;
      fragment.appendChild(anchor);

      cursor = match.end;
    }

    // Remaining text after the last match.
    if (cursor < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(cursor)));
    }

    textNode.parentNode?.replaceChild(fragment, textNode);
    didReplace = true;
  }

  return didReplace;
}

/**
 * React component that mounts a MutationObserver on the chat messages
 * container and linkifies any local paths found in rendered text.
 *
 * Place this inside the chat page so it can find the message list via
 * a CSS selector.
 */
export function LocalPathLinkifier() {
  const observerRef = useRef<MutationObserver | null>(null);
  const clickHandlerRef = useRef<((e: MouseEvent) => void) | null>(null);

  useEffect(() => {
    if (!isDesktopApp()) return;

    // We observe document.body so the observer works regardless of CSS
    // module class-name hashing.  The PROCESSED_ATTR guard keeps the
    // scan cheap — each element is processed at most once.
    const root = document.body;
    if (!root) return;

    // --- MutationObserver: scan new / changed subtrees -----------------
    const processElement = (el: HTMLElement) => {
      // Skip already-processed elements (their text hasn't changed).
      if (el.getAttribute?.(PROCESSED_ATTR) === "1") return;
      // Skip code blocks (<pre><code>) and our own injected links.
      // NOTE: inline <code> is NOT skipped — paths wrapped in backticks by
      // the markdown renderer should still be linkified.
      if (el.tagName === "PRE" || el.classList?.contains(LINK_CLASS)) return;
      if (el.tagName === "CODE" && el.parentElement?.tagName === "PRE") return;

      linkifyTextNode(el);
      el.setAttribute?.(PROCESSED_ATTR, "1");
    };

    const processMutations = (mutations: MutationRecord[]) => {
      for (const mutation of mutations) {
        // New nodes added to the DOM.
        if (mutation.type === "childList") {
          for (const node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            processElement(node as HTMLElement);
          }
        }
        // Text content changed inside an existing element.
        if (
          mutation.type === "characterData" &&
          mutation.target.nodeType === Node.TEXT_NODE
        ) {
          const parent = (mutation.target as Text).parentElement;
          if (parent) {
            // Clear the processed flag so the element gets re-scanned.
            parent.removeAttribute?.(PROCESSED_ATTR);
            processElement(parent);
          }
        }
      }
    };

    const observer = new MutationObserver(processMutations);
    observer.observe(root, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    observerRef.current = observer;

    // Initial scan for content already present (do NOT mark body as
    // processed — that would prevent the observer from handling future
    // mutations on body's descendants).
    linkifyTextNode(root);

    // --- Click delegation ----------------------------------------------
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.classList?.contains(LINK_CLASS)) return;

      e.preventDefault();
      e.stopPropagation();

      const path = target.getAttribute(DATA_PATH_ATTR);
      if (path) {
        void openInExplorer(path);
      }
    };

    document.addEventListener("click", handleClick, true);
    clickHandlerRef.current = handleClick;

    // --- Cleanup -------------------------------------------------------
    return () => {
      observer.disconnect();
      observerRef.current = null;
      if (clickHandlerRef.current) {
        document.removeEventListener("click", clickHandlerRef.current, true);
        clickHandlerRef.current = null;
      }
    };
  }, []);

  // This component renders nothing visible.
  return null;
}
