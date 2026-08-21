import { useEffect } from "react";

export function useGlobalAnimationPauser() {
  useEffect(() => {
    if (
      typeof IntersectionObserver === "undefined" ||
      typeof MutationObserver === "undefined"
    ) {
      return;
    }

    // We want to pause infinite CSS animations (like spinners) when they are offscreen
    // to save CPU, especially for Tauri WebKit where idle CPU can sit at ~20%.
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const el = entry.target as HTMLElement;
          if (entry.isIntersecting) {
            el.style.animationPlayState = "running";
          } else {
            el.style.animationPlayState = "paused";
          }
        });
      },
      { threshold: 0 },
    );

    const observeNode = (node: HTMLElement) => {
      // Check if it's an element that typically spins infinitely
      if (
        node.classList &&
        (node.classList.contains("ant-spin") ||
          node.classList.contains("ant-spin-dot") ||
          node.classList.contains("ant-spin-dot-spin") ||
          node.classList.contains("ant-spin-dot-item") ||
          node.className.toString().includes("ai-copilot-blink"))
      ) {
        observer.observe(node);
      }
      // Also check children
      if (node.querySelectorAll) {
        const spinners = node.querySelectorAll(
          ".ant-spin, .ant-spin-dot, .ant-spin-dot-spin, .ant-spin-dot-item, [class*='ai-copilot-blink']",
        );
        spinners.forEach((spin) => observer.observe(spin));
      }
    };

    const mutationObserver = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        mutation.removedNodes.forEach((node) => {
          if (node.nodeType === Node.ELEMENT_NODE) {
            const el = node as HTMLElement;
            observer.unobserve(el);
            if (el.querySelectorAll) {
              const spinners = el.querySelectorAll(
                ".ant-spin, .ant-spin-dot, .ant-spin-dot-spin, .ant-spin-dot-item, [class*='ai-copilot-blink']",
              );
              spinners.forEach((spin) => observer.unobserve(spin));
            }
          }
        });
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === Node.ELEMENT_NODE) {
            observeNode(node as HTMLElement);
          }
        });
      });
    });

    // Initial pass
    observeNode(document.body);

    mutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
    });

    return () => {
      observer.disconnect();
      mutationObserver.disconnect();
    };
  }, []);
}
