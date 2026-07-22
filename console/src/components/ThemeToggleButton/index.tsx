import { Dropdown, Button, type MenuProps } from "antd";
import { SparkMoonLine, SparkSunLine } from "@agentscope-ai/icons";
import { Check, Edit3, Star, SunMoon } from "lucide-react";
import {
  getThemePresetGradient,
  isBuiltInThemePreset,
  sortThemePresets,
  useTheme,
  type ThemeMode,
  type ThemePreset,
} from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import type { CSSProperties, MouseEvent, ReactNode } from "react";
import styles from "./index.module.less";

const ICONS: Record<ThemeMode, ReactNode> = {
  light: <SparkSunLine />,
  dark: <SparkMoonLine />,
  system: <SunMoon size="1em" />,
};

export default function ThemeToggleButton() {
  const {
    themeMode,
    isDark,
    setThemeMode,
    themePresets,
    activeThemePresetId,
    selectThemePreset,
    toggleThemePresetFavorite,
  } = useTheme();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const quickPresets = sortThemePresets(themePresets).filter((preset) => {
    return !isBuiltInThemePreset(preset) || preset.favorite;
  });

  const openThemeEditor = () => {
    navigate("/agent-config?tab=theme");
  };

  const updateThemeEditorPresetParam = (presetId: string | null) => {
    const searchParams = new URLSearchParams(location.search);
    if (
      location.pathname !== "/agent-config" ||
      searchParams.get("tab") !== "theme"
    ) {
      return;
    }

    if (presetId) {
      searchParams.set("preset", presetId);
    } else {
      searchParams.delete("preset");
    }
    navigate(`${location.pathname}?${searchParams.toString()}`, {
      replace: true,
    });
  };

  const selectPresetFromMenu = (presetId: string) => {
    selectThemePreset(presetId);
    updateThemeEditorPresetParam(presetId);
  };

  const selectSystemTheme = () => {
    setThemeMode("system");
    updateThemeEditorPresetParam(null);
  };

  const editThemePreset = (preset: ThemePreset) => {
    selectThemePreset(preset.id);
    navigate(`/agent-config?tab=theme&preset=${encodeURIComponent(preset.id)}`);
  };

  const toggleFavorite = (
    event: MouseEvent<HTMLButtonElement>,
    presetId: string,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    toggleThemePresetFavorite(presetId);
  };

  const editPreset = (
    event: MouseEvent<HTMLButtonElement>,
    preset: ThemePreset,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    editThemePreset(preset);
  };

  const presetItems: MenuProps["items"] = quickPresets.map((preset) => {
    const active = preset.id === activeThemePresetId;
    return {
      key: `preset-${preset.id}`,
      label: (
        <div className={styles.themePresetMenuItem}>
          <span
            className={styles.themePresetMenuSwatch}
            style={
              {
                "--theme-preset-gradient": getThemePresetGradient(
                  preset.colors,
                ),
              } as CSSProperties
            }
          />
          <span className={styles.themePresetMenuName}>{preset.name}</span>
          {active && (
            <Check size={14} className={styles.themePresetMenuCheck} />
          )}
          <button
            type="button"
            className={`${styles.themePresetMenuAction} ${
              preset.favorite ? styles.themePresetMenuActionActive : ""
            }`}
            onClick={(event) => toggleFavorite(event, preset.id)}
            aria-label={t("themeEditor.favorite", "Favorite")}
          >
            <Star size={14} fill={preset.favorite ? "currentColor" : "none"} />
          </button>
          <button
            type="button"
            className={styles.themePresetMenuAction}
            onClick={(event) => editPreset(event, preset)}
            aria-label={t("common.edit")}
          >
            <Edit3 size={14} />
          </button>
        </div>
      ),
      onClick: () => selectPresetFromMenu(preset.id),
    };
  });

  const items: MenuProps["items"] = [
    ...presetItems,
    {
      key: "system",
      label: t("theme.system"),
      onClick: selectSystemTheme,
    },
    {
      type: "divider",
    },
    {
      key: "customize",
      label: t("theme.customize", "Customize"),
      onClick: openThemeEditor,
    },
  ];

  const icon =
    themeMode === "system" ? ICONS.system : ICONS[isDark ? "dark" : "light"];

  return (
    <Dropdown
      menu={{
        items,
        selectedKeys: [themeMode, `preset-${activeThemePresetId}`],
      }}
      placement="bottomRight"
      overlayClassName={styles.themeDropdown}
    >
      <Button className={styles.toggleBtn} type="text" icon={icon} />
    </Dropdown>
  );
}
