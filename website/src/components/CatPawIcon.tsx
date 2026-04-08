/**
 * CoPaw branding logo (logo.png). Favicon uses copaw-symbol.svg.
 */
interface CatPawIconProps {
  size: number;
  className?: string;
}

const LOGO_SRC =
  "https://img.alicdn.com/imgextra/i1/O1CN0187d8Zq1U51Qw6WTtl_!!6000000002465-2-tps-4167-981.png";

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
