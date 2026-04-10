/**
 * QwenPaw mascot (same as logo symbol). Used in Hero and Nav.
 */
import { CatPawIcon } from "./CatPawIcon";

interface QwenpawMascotProps {
  size?: number;
  className?: string;
}

export function QwenpawMascot({
  size = 80,
  className = "",
}: QwenpawMascotProps) {
  return <CatPawIcon size={size} className={className} />;
}
