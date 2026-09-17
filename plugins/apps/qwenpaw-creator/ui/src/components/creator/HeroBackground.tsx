/**
 * Animated home hero backdrop: the draft's white page with a soft #FF6A00
 * glow cluster on the left edge.  Blobs share one oversized blurred canvas
 * so no edges surface, each looping a slow orbit (disabled under
 * prefers-reduced-motion).
 */

const BLOBS: {
  style: React.CSSProperties;
  drift: { dx: string; dy: string };
  duration: string;
  delay: string;
}[] = [
  {
    style: {
      left: "-10%",
      top: "32%",
      width: "34%",
      height: "42%",
      background: "rgba(255, 106, 0, 0.17)",
    },
    drift: { dx: "3vw", dy: "-3vh" },
    duration: "26s",
    delay: "0s",
  },
  {
    style: {
      left: "6%",
      top: "12%",
      width: "22%",
      height: "26%",
      background: "rgba(255, 145, 60, 0.10)",
    },
    drift: { dx: "-2vw", dy: "3vh" },
    duration: "32s",
    delay: "-12s",
  },
  {
    style: {
      left: "20%",
      top: "48%",
      width: "24%",
      height: "28%",
      background: "rgba(255, 106, 0, 0.06)",
    },
    drift: { dx: "4vw", dy: "2vh" },
    duration: "29s",
    delay: "-20s",
  },
];

export default function HeroBackground() {
  return (
    <div className="hero-bg" aria-hidden="true">
      <div className="hero-bg-canvas">
        {BLOBS.map((blob, index) => (
          <span
            key={index}
            className="hero-bg-blob"
            style={
              {
                ...blob.style,
                "--drift-x": blob.drift.dx,
                "--drift-y": blob.drift.dy,
                animationDuration: blob.duration,
                animationDelay: blob.delay,
              } as React.CSSProperties
            }
          />
        ))}
      </div>
    </div>
  );
}
