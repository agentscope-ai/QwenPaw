/**
 * QwenPaw logo: symbol only. When logo and brand text would both appear,
 * we show only the logo (no separate text).
 */
import { CatPawIcon } from "./CatPawIcon";

interface QwenpawLogoProps {
  variant?: "full" | "mark";
  size?: number;
  animated?: boolean;
  className?: string;
}

export function QwenpawLogo({
  variant = "full",
  size = 48,
  animated: _animated = false,
  className = "",
}: QwenpawLogoProps) {
  const markSize = variant === "mark" ? size : Math.round(size * 1.1);
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", lineHeight: 1 }}
    >
      <CatPawIcon size={markSize} />
    </span>
  );
}
