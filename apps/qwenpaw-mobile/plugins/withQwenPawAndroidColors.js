const {
  AndroidConfig,
  withAndroidColors,
  withAndroidColorsNight,
} = require("@expo/config-plugins");

const lightColors = Object.freeze({
  qwenpaw_canvas: "#EBE7DF",
  qwenpaw_grouped_background: "#F6F3ED",
  qwenpaw_surface: "#FFFDF9",
  qwenpaw_surface_strong: "#FFFFFF",
  qwenpaw_surface_soft: "#EEEAE2",
  qwenpaw_tab_bar: "#FFFDF9",
  qwenpaw_search_background: "#EEEAE2",
  qwenpaw_pressed: "#E7E1D8",
  qwenpaw_ink: "#1D1B18",
  qwenpaw_muted: "#66615B",
  qwenpaw_faint: "#6D6760",
  qwenpaw_line: "#E4DDD4",
  qwenpaw_hairline: "#DED6CC",
  qwenpaw_accent_dark: "#A94008",
  qwenpaw_accent_soft: "#FFF0E5",
  qwenpaw_positive: "#2F7B56",
  qwenpaw_danger: "#A63F39",
  qwenpaw_scrim: "#4D140F0C",
});

const darkColors = Object.freeze({
  qwenpaw_canvas: "#0E0D0C",
  qwenpaw_grouped_background: "#151412",
  qwenpaw_surface: "#211F1C",
  qwenpaw_surface_strong: "#2E2B27",
  qwenpaw_surface_soft: "#2A2723",
  qwenpaw_tab_bar: "#211F1C",
  qwenpaw_search_background: "#2A2723",
  qwenpaw_pressed: "#35312C",
  qwenpaw_ink: "#F6F1E9",
  qwenpaw_muted: "#AAA39A",
  qwenpaw_faint: "#8E877F",
  qwenpaw_line: "#37332E",
  qwenpaw_hairline: "#3D3933",
  qwenpaw_accent_dark: "#FFA06B",
  qwenpaw_accent_soft: "#3B261B",
  qwenpaw_positive: "#70C496",
  qwenpaw_danger: "#FF8B83",
  qwenpaw_scrim: "#9E000000",
});

function applyColors(resourceXml, palette) {
  return Object.entries(palette).reduce(
    (result, [name, value]) => AndroidConfig.Colors.assignColorValue(
      result,
      { name, value },
    ),
    resourceXml,
  );
}

function withQwenPawAndroidColors(config) {
  config = withAndroidColors(config, (androidConfig) => {
    androidConfig.modResults = applyColors(
      androidConfig.modResults,
      lightColors,
    );
    return androidConfig;
  });

  return withAndroidColorsNight(config, (androidConfig) => {
    androidConfig.modResults = applyColors(
      androidConfig.modResults,
      darkColors,
    );
    return androidConfig;
  });
}

module.exports = withQwenPawAndroidColors;
module.exports.lightColors = lightColors;
module.exports.darkColors = darkColors;
