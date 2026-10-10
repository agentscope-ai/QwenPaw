import type { ReactElement } from "react";

/**
 * Letter badge matching the icon set's language badges (a rounded
 * frame around a language code), used where the icon set has no
 * dedicated glyph.
 *
 * Frame geometry is measured from the real badges: outer box
 * 117.12..906.88, inner box 181.12..842.88, so the ring is 64 wide
 * with a 152.96 radius inside a 1024 viewBox.  Stroking the centre
 * line of that ring reproduces it exactly.
 */
export default function LanguageBadge({
  code,
}: {
  code: string;
}): ReactElement {
  return (
    // Same wrapper the icon set's own components use. The design
    // system sizes button icons via `span[data-spark-icon]`, so the
    // attribute is required for this badge to match real ones.
    <span
      className="spark-icon"
      data-spark-icon="true"
      role="img"
      aria-label={`language-${code}`}
    >
      <svg
        width="1em"
        height="1em"
        viewBox="0 0 1024 1024"
        overflow="hidden"
        fill="currentColor"
        aria-hidden="true"
      >
        <rect
          x="149.12"
          y="149.12"
          width="725.76"
          height="725.76"
          rx="120.96"
          fill="none"
          stroke="currentColor"
          strokeWidth="64"
        />
        <text
          x="512"
          y="512"
          textAnchor="middle"
          dominantBaseline="central"
          fontSize="460"
          fontWeight="500"
          fill="currentColor"
        >
          {code}
        </text>
      </svg>
    </span>
  );
}
