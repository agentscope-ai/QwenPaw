/**
 * Renders a monochrome SVG through a CSS mask so the glyph follows
 * `currentColor` despite the exported assets carrying hard-coded fills.
 */
export default function MaskIcon({
  src,
  size = 18,
  className = "",
}: {
  src: string;
  size?: number;
  className?: string;
}) {
  // Vite inlines small assets as data URIs, only valid inside a quoted url().
  const maskUrl = `url("${src}")`;
  return (
    <span
      aria-hidden="true"
      className={`inline-block shrink-0 bg-current ${className}`}
      style={{
        width: size,
        height: size,
        WebkitMaskImage: maskUrl,
        maskImage: maskUrl,
        WebkitMaskSize: "100% 100%",
        maskSize: "100% 100%",
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
      }}
    />
  );
}
