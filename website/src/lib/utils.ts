import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Shared section heading styles
export const sectionStyles = {
  // Main section title (e.g., "Do it yourself, done easily.")
  title:
    "font-newsreader text-3xl font-semibold leading-[1] text-(--color-text) md:text-4xl",
  // Section subtitle/description
  subtitle:
    "font-inter text-[13px] leading-[1.2] text-(--color-text-tertiary) md:text-[1rem]",
} as const;
