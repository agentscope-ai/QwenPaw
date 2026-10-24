import { beforeEach, expect, it, vi } from "vitest";
import { useTranslation } from "../src/locale";

const locale = vi.hoisted(() => ({ value: "en" }));
vi.mock("../src/host", () => ({
  host: { useLocale: () => locale.value },
}));

beforeEach(() => {
  locale.value = "en";
});

it.each([
  ["en-US", "Cancel"],
  ["zh_CN", "取消"],
  ["ja", "キャンセル"],
  ["pt-BR", "Cancelar"],
  ["ru", "Отмена"],
  ["vi", "Hủy"],
  ["id", "Batal"],
])("resolves the plugin-owned cancel label for %s", (language, expected) => {
  locale.value = language;
  expect(useTranslation().t("desktop.recording.cancel")).toBe(expected);
});

it("falls back to English for an unsupported host locale", () => {
  locale.value = "fr-FR";
  expect(useTranslation().t("desktop.recording.cancel")).toBe("Cancel");
});

it("falls back to English for a message not yet translated", () => {
  locale.value = "ja";
  expect(useTranslation().t("desktop.recording.learn.modelUnavailable")).toBe(
    "Configure and select a model in Models settings, then retry. Your recording is still saved.",
  );
});

it("substitutes values using the selected locale", () => {
  locale.value = "zh-CN";
  expect(
    useTranslation().t("desktop.recording.learn.created", { name: "example" }),
  ).toBe("Skill example 已创建并启用");
});
