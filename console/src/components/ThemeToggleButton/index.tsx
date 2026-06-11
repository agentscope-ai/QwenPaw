import { Sun, Moon, SunMoon } from "lucide-react";
import { useTheme, type ThemeMode } from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ICONS: Record<ThemeMode, ReactNode> = {
  light: <Sun className="h-[1em] w-[1em]" />,
  dark: <Moon className="h-[1em] w-[1em]" />,
  system: <SunMoon className="h-[1em] w-[1em]" />,
};

export default function ThemeToggleButton() {
  const { themeMode, isDark, setThemeMode } = useTheme();
  const { t } = useTranslation();

  const icon =
    themeMode === "system" ? ICONS.system : ICONS[isDark ? "dark" : "light"];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8">
          {icon}
          <span className="sr-only">Toggle theme</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() => setThemeMode("light")}
          className={cn(themeMode === "light" && "bg-accent")}
        >
          <Sun className="h-4 w-4" />
          {t("theme.light")}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => setThemeMode("dark")}
          className={cn(themeMode === "dark" && "bg-accent")}
        >
          <Moon className="h-4 w-4" />
          {t("theme.dark")}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => setThemeMode("system")}
          className={cn(themeMode === "system" && "bg-accent")}
        >
          <SunMoon className="h-4 w-4" />
          {t("theme.system")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
