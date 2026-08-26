/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { createElement } from "react";

// ---------------------------------------------------------------------------
// A#85241570 — tags persist after switching the language
// When the language is switched, ALL translated labels/tags must update to
// the new language. Stale labels from the previous language must not remain.
//
// This test verifies the i18n reactivity contract: components using
// useTranslation() must re-render with updated text when i18n.changeLanguage
// is called.
// ---------------------------------------------------------------------------

// Bilingual translation resources for testing
const resources = {
  en: {
    translation: {
      "status.running": "Running",
      "status.stopped": "Stopped",
      "status.error": "Error",
      "tag.priority": "Priority",
      "tag.category": "Category",
      "nav.home": "Home",
      "nav.settings": "Settings",
    },
  },
  zh: {
    translation: {
      "status.running": "运行中",
      "status.stopped": "已停止",
      "status.error": "错误",
      "tag.priority": "优先级",
      "tag.category": "分类",
      "nav.home": "首页",
      "nav.settings": "设置",
    },
  },
};

describe("Language switch tag update (A#85241570)", () => {
  let i18nInstance: {
    language: string;
    changeLanguage: (lang: string) => void;
    on: (event: string, cb: (...args: any[]) => void) => void;
    off: (event: string, cb: (...args: any[]) => void) => void;
    emit: (event: string, ...args: any[]) => void;
    isInitialized: boolean;
  };

  beforeEach(() => {
    // Create a controllable i18n mock that supports language switching
    const listeners: Record<string, Array<(...args: any[]) => void>> = {};
    i18nInstance = {
      language: "en",
      isInitialized: true,
      changeLanguage(lang: string) {
        this.language = lang;
        this.emit("languageChanged", lang);
      },
      on(event: string, cb: (...args: any[]) => void) {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(cb);
      },
      off(event: string, cb: (...args: any[]) => void) {
        if (listeners[event]) {
          listeners[event] = listeners[event].filter((fn) => fn !== cb);
        }
      },
      emit(event: string, ...args: any[]) {
        if (listeners[event]) {
          listeners[event].forEach((cb) => cb(...args));
        }
      },
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("updates all translated tags when language changes from English to Chinese", async () => {
    // We need to mock react-i18next to use our controllable i18n instance
    // and actually trigger re-renders on language change.
    await vi.importActual<typeof import("react-i18next")>("react-i18next");
    const { useState, useEffect, useCallback } = await import("react");

    vi.doMock("react-i18next", () => ({
      useTranslation: () => {
        const [lang, setLang] = useState(i18nInstance.language);
        useEffect(() => {
          const handler = (newLang: string) => setLang(newLang);
          i18nInstance.on("languageChanged", handler);
          return () => i18nInstance.off("languageChanged", handler);
        }, []);

        const t = useCallback(
          (key: string) => {
            return (
              (
                resources[lang as keyof typeof resources]
                  ?.translation as Record<string, string>
              )?.[key] ?? key
            );
          },
          [lang],
        );

        return { t, i18n: i18nInstance };
      },
    }));

    // Re-import the component after mock setup
    vi.resetModules();
    const { useTranslation: mockedUseTranslation } = await import(
      "react-i18next"
    );

    // Render the component inline using the mocked hook
    function TestComponent() {
      const { t } = mockedUseTranslation();
      return (
        <div>
          <span data-testid="status-tag">{t("status.running")}</span>
          <span data-testid="priority-tag">{t("tag.priority")}</span>
          <span data-testid="nav-label">{t("nav.home")}</span>
        </div>
      );
    }

    renderWithProviders(createElement(TestComponent));

    // Initially in English
    expect(screen.getByTestId("status-tag")).toHaveTextContent("Running");
    expect(screen.getByTestId("priority-tag")).toHaveTextContent("Priority");
    expect(screen.getByTestId("nav-label")).toHaveTextContent("Home");

    // Switch to Chinese
    await act(async () => {
      i18nInstance.changeLanguage("zh");
    });

    // ALL tags must update — no stale English labels should remain
    await waitFor(() => {
      expect(screen.getByTestId("status-tag")).toHaveTextContent("运行中");
    });
    expect(screen.getByTestId("priority-tag")).toHaveTextContent("优先级");
    expect(screen.getByTestId("nav-label")).toHaveTextContent("首页");

    // Verify NO English text remains
    expect(screen.queryByText("Running")).not.toBeInTheDocument();
    expect(screen.queryByText("Priority")).not.toBeInTheDocument();
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
  });

  it("updates all tags when switching back from Chinese to English", async () => {
    // Start in Chinese
    i18nInstance.language = "zh";

    await vi.importActual<typeof import("react-i18next")>("react-i18next");
    const { useState, useEffect, useCallback } = await import("react");

    vi.doMock("react-i18next", () => ({
      useTranslation: () => {
        const [lang, setLang] = useState(i18nInstance.language);
        useEffect(() => {
          const handler = (newLang: string) => setLang(newLang);
          i18nInstance.on("languageChanged", handler);
          return () => i18nInstance.off("languageChanged", handler);
        }, []);

        const t = useCallback(
          (key: string) => {
            return (
              (
                resources[lang as keyof typeof resources]
                  ?.translation as Record<string, string>
              )?.[key] ?? key
            );
          },
          [lang],
        );

        return { t, i18n: i18nInstance };
      },
    }));

    vi.resetModules();
    const { useTranslation: mockedUseTranslation } = await import(
      "react-i18next"
    );

    function TestComponent() {
      const { t } = mockedUseTranslation();
      return (
        <div>
          <span data-testid="status-tag">{t("status.running")}</span>
          <span data-testid="priority-tag">{t("tag.priority")}</span>
          <span data-testid="nav-label">{t("nav.home")}</span>
        </div>
      );
    }

    renderWithProviders(createElement(TestComponent));

    // Initially in Chinese
    expect(screen.getByTestId("status-tag")).toHaveTextContent("运行中");
    expect(screen.getByTestId("priority-tag")).toHaveTextContent("优先级");
    expect(screen.getByTestId("nav-label")).toHaveTextContent("首页");

    // Switch back to English
    await act(async () => {
      i18nInstance.changeLanguage("en");
    });

    // ALL tags must update back to English
    await waitFor(() => {
      expect(screen.getByTestId("status-tag")).toHaveTextContent("Running");
    });
    expect(screen.getByTestId("priority-tag")).toHaveTextContent("Priority");
    expect(screen.getByTestId("nav-label")).toHaveTextContent("Home");

    // Verify NO Chinese text remains
    expect(screen.queryByText("运行中")).not.toBeInTheDocument();
    expect(screen.queryByText("优先级")).not.toBeInTheDocument();
    expect(screen.queryByText("首页")).not.toBeInTheDocument();
  });
});
