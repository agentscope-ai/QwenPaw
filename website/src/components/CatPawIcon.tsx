/**
 * CoPaw branding logo (logo.png). Favicon uses copaw-symbol.svg.
 */
interface CatPawIconProps {
  size: number;
  className?: string;
}

const LOGO_SRC = "/logo.png";

export function CatPawIcon({ size, className = "" }: CatPawIconProps) {
  return (
    <img
      src={LOGO_SRC}
      alt=""
      width={size}
      height={size}
      className={className}
      style={{
        display: "block",
        margin: "0 auto",
        objectFit: "contain",
      }}
      aria-hidden
    />
  );
}
