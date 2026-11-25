import { getHost } from "@qwenpaw/plugin-sdk";
import { Settings } from "./Settings";
getHost().harnesses.register("qwenpaw-harness-agy", {
  backendId: "agy",
  SettingsComponent: Settings,
});
