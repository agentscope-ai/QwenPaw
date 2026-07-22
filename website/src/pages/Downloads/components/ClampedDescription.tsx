import { useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const TEXT_CLASS = "block w-full text-sm leading-relaxed text-site-text-muted";

function useIsTextClamped(
  visibleRef: React.RefObject<HTMLElement | null>,
  fullRef: React.RefObject<HTMLElement | null>,
  text: string,
) {
  const [isClamped, setIsClamped] = useState(false);

  useLayoutEffect(() => {
    const visible = visibleRef.current;
    const full = fullRef.current;
    if (!visible || !full) return;

    const measure = () => {
      setIsClamped(full.offsetHeight > visible.offsetHeight + 1);
    };

    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(visible);
    if (visible.parentElement) {
      observer.observe(visible.parentElement);
    }

    return () => observer.disconnect();
  }, [visibleRef, fullRef, text]);

  return isClamped;
}

interface ClampedDescriptionProps {
  text: string;
  className?: string;
}

export function ClampedDescription({
  text,
  className,
}: ClampedDescriptionProps) {
  const visibleRef = useRef<HTMLSpanElement>(null);
  const fullRef = useRef<HTMLSpanElement>(null);
  const isClamped = useIsTextClamped(visibleRef, fullRef, text);

  return (
    <div
      className={cn(
        "group/desc relative w-full",
        isClamped && "cursor-default",
      )}
    >
      <span
        ref={visibleRef}
        className={cn(TEXT_CLASS, "line-clamp-2", className)}
      >
        {text}
      </span>

      {/* 无 line-clamp 的镜像，用于可靠判断是否溢出 */}
      <span
        ref={fullRef}
        aria-hidden
        className={cn(
          TEXT_CLASS,
          "pointer-events-none invisible absolute top-0 right-0 left-0 -z-10 h-auto",
        )}
      >
        {text}
      </span>

      {isClamped && (
        <div
          role="tooltip"
          className={cn(
            "absolute bottom-full left-0 z-50 mb-1 hidden max-h-60 max-w-md overflow-y-auto",
            "rounded-md border border-border bg-surface px-3 py-2.5 text-sm leading-relaxed text-site-text shadow-lg",
            "group-hover/desc:block",
            "before:absolute before:inset-x-0 before:top-full before:h-2 before:content-['']",
          )}
        >
          {text}
        </div>
      )}
    </div>
  );
}
