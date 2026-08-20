import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

const DEFAULT_ESTIMATED_HEIGHT_PX = 240;
const VIEWPORT_OVERSCAN_PX = 1200;

type VisibilityListener = (isNearViewport: boolean) => void;

const visibilityListeners = new WeakMap<Element, VisibilityListener>();
let sharedObserver: IntersectionObserver | null = null;

function getSharedObserver(): IntersectionObserver | null {
  if (typeof IntersectionObserver === "undefined") return null;
  if (sharedObserver) return sharedObserver;

  sharedObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        visibilityListeners.get(entry.target)?.(entry.isIntersecting);
      });
    },
    {
      rootMargin: `${VIEWPORT_OVERSCAN_PX}px 0px`,
    },
  );
  return sharedObserver;
}

function observeVisibility(
  element: Element,
  listener: VisibilityListener,
): () => void {
  const observer = getSharedObserver();
  if (!observer) return () => undefined;

  visibilityListeners.set(element, listener);
  observer.observe(element);
  return () => {
    observer.unobserve(element);
    visibilityListeners.delete(element);
  };
}

interface ViewportRenderBoundaryProps {
  children: React.ReactNode;
  estimatedHeight?: number;
}

/**
 * Keep expensive chat-card content mounted only near the viewport.
 *
 * The outer element always remains in the SDK bubble tree. Once its real
 * height has been measured, offscreen content can be removed without changing
 * scroll geometry. One shared IntersectionObserver serves every chat card.
 */
export const ViewportRenderBoundary = React.memo(
  function ViewportRenderBoundary({
    children,
    estimatedHeight = DEFAULT_ESTIMATED_HEIGHT_PX,
  }: ViewportRenderBoundaryProps) {
    const elementRef = useRef<HTMLDivElement>(null);
    const measuredHeightRef = useRef(estimatedHeight);
    const [isNearViewport, setIsNearViewport] = useState(true);

    useLayoutEffect(() => {
      const element = elementRef.current;
      if (!element || !isNearViewport) return;

      const rememberHeight = () => {
        const height = element.getBoundingClientRect().height;
        if (height > 0) measuredHeightRef.current = height;
      };

      rememberHeight();
      if (typeof ResizeObserver === "undefined") return;

      const resizeObserver = new ResizeObserver(rememberHeight);
      resizeObserver.observe(element);
      return () => resizeObserver.disconnect();
    }, [isNearViewport, children]);

    useEffect(() => {
      const element = elementRef.current;
      if (!element) return;
      return observeVisibility(element, setIsNearViewport);
    }, []);

    return (
      <div
        ref={elementRef}
        data-chat-viewport-content={isNearViewport ? "mounted" : "deferred"}
        style={
          isNearViewport
            ? undefined
            : {
                height: measuredHeightRef.current,
                contain: "strict",
              }
        }
      >
        {isNearViewport ? children : null}
      </div>
    );
  },
);
