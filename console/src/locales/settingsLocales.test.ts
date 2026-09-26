import { describe, expect, it } from "vitest";
import en from "./en.json";
import zh from "./zh.json";
import ja from "./ja.json";
import ru from "./ru.json";
import pt from "./pt-BR.json";
import id from "./id.json";
import vi from "./vi.json";
function flatten(value: object, prefix = ""): Record<string, string> {
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]) =>
      typeof item === "string"
        ? [[`${prefix}${key}`, item]]
        : Object.entries(flatten(item, `${prefix}${key}.`)),
    ),
  );
}
const navigationKeys = [
  "sidebarEditHelp",
  "fixedEntry",
  "addEntry",
  "allAdded",
  "availableEntries",
  "dropHere",
  "moveEntry",
  "removeEntry",
  "sidebarPreview",
] as const;
describe("settings localization", () => {
  for (const [language, resource] of Object.entries({
    zh,
    ja,
    ru,
    pt,
    id,
    vi,
  })) {
    it(`${language} covers settings strings and preserves interpolation placeholders`, () => {
      const source = {
        ...flatten(en.cronJobs, "cronJobs."),
        ...flatten(en.channels, "channels."),
        ...flatten(en.heartbeat, "heartbeat."),
        ...flatten(en.skills, "skills."),
        ...flatten(en.tools, "tools."),
        ...Object.fromEntries(
          navigationKeys.map((key) => [key, en.settingsCenter[key]]),
        ),
      };
      const target = {
        ...flatten(resource.cronJobs, "cronJobs."),
        ...flatten(resource.channels, "channels."),
        ...flatten(resource.heartbeat, "heartbeat."),
        ...flatten(resource.skills, "skills."),
        ...flatten(resource.tools, "tools."),
        ...Object.fromEntries(
          navigationKeys.map((key) => [key, resource.settingsCenter[key]]),
        ),
      };
      for (const [key, text] of Object.entries(source)) {
        expect(target[key], key).toBeTruthy();
        expect(target[key].match(/\{\{.*?\}\}/g)?.sort() ?? [], key).toEqual(
          text.match(/\{\{.*?\}\}/g)?.sort() ?? [],
        );
      }
    });
  }
});
