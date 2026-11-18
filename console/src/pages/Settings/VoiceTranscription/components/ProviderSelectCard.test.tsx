// @vitest-environment jsdom
/**
 * ProviderSelectCard - the "Whisper API Provider" picker of Settings > Voice
 * Transcription. Rendered from one place, checked by grep before this suite was
 * written:
 *   - `pages/Settings/VoiceTranscription/index.tsx:78` (imported through the
 *     `./components` barrel at `:9`), and only while `isWhisperApi` holds.
 *
 * Visible contract under test:
 *
 *   1. the card has TWO mutually exclusive shapes, decided solely by
 *      `availableProviders.length === 0`: no providers -> a warning alert and NO
 *      select at all; one or more -> a select and NO alert. Both halves are
 *      pinned in both directions, because an empty picker would let the user
 *      save a transcription backend that has nothing to call;
 *   2. in the empty shape the warning carries only a message, no description;
 *   3. one option per provider, in the order the parent supplied, with the
 *      provider `id` as the option value and the provider `name` as its visible
 *      text - so two providers with the same display name stay distinct;
 *   4. `selectedProviderId` is normalized on the way in: an empty string is
 *      turned into `undefined`, which is what makes the placeholder show instead
 *      of an empty selection. This mirrors the channel normalization in
 *      `Control/Sessions/components/FilterBar.tsx`;
 *   5. the placeholder is the translated `providerPlaceholder` key;
 *   6. picking an option hands the parent the RAW ID STRING - `onChange` is
 *      passed straight through, so antd's second argument (the option data)
 *      reaches the parent too. That is pinned rather than assumed, because the
 *      parent stores the value in state. Re-picking the provider that is
 *      already selected emits nothing at all, so the parent is never asked to
 *      re-save what it has;
 *   6b. two providers with the SAME display name stay distinct, but only
 *      through the id each click emits: antd renders the name into both the
 *      option text and its `title`, so the DOM cannot tell them apart;
 *   7. the select is full width but capped: the product sets
 *      `{ width: "100%", maxWidth: 400 }` inline, which is the one layout
 *      attribute it owns instead of leaving to CSS;
 *   8. every visible string is an i18n key from the `voiceTranscription`
 *      namespace.
 *
 * Harness notes (measured facts, not guesses):
 *
 * - antd renders for real here (`Card, Select, Alert` come from `antd`, which
 *   `vite.config.ts` does not alias). Probes measured: `.ant-select` carries the
 *   inline style as `width: 100%; max-width: 400px;`; `.ant-select-selection-
 *   placeholder` holds the placeholder text only when `value` is `undefined`;
 *   `.ant-select-selection-item` holds the chosen provider's name AND a `title`
 *   attribute; the dropdown opens on `mouseDown` of `.ant-select-selector` and
 *   its options land in `.ant-select-item-option`; clicking one calls `onChange`
 *   with `("p2", { key, value, children })`.
 * - `react-i18next` IS mocked with `t` returning the key verbatim, so assertions
 *   pin the i18n key the product asks for. Keys were read back from
 *   `src/locales/en.json`, not typed from memory.
 * - `@agentscope-ai/design` is not imported by this component, so the shared
 *   design stub stays untouched.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import type { TranscriptionProvider } from "../useVoiceTranscription";
import styles from "../index.module.less";

vi.mock("react-i18next", () => {
  // Built once per factory call so `t` keeps a stable identity across renders.
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key;
  return {
    useTranslation: () => ({
      t,
      i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
    }),
  };
});

import { ProviderSelectCard } from "./ProviderSelectCard";

const TWO_PROVIDERS: TranscriptionProvider[] = [
  { id: "openai", name: "OpenAI", available: true },
  { id: "ollama", name: "Ollama Local", available: true },
];

function renderCard(props: {
  availableProviders?: TranscriptionProvider[];
  selectedProviderId?: string;
  onProviderChange?: (id: string) => void;
}) {
  const onProviderChange = props.onProviderChange ?? vi.fn();
  const view = render(
    <ProviderSelectCard
      availableProviders={props.availableProviders ?? TWO_PROVIDERS}
      selectedProviderId={props.selectedProviderId ?? ""}
      onProviderChange={onProviderChange}
    />,
  );
  return { ...view, onProviderChange };
}

function selectOf(container: HTMLElement): HTMLElement | null {
  return container.querySelector(".ant-select");
}

/** Opens the dropdown; antd renders the options into the document body. */
function openDropdown(container: HTMLElement): void {
  fireEvent.mouseDown(
    container.querySelector(".ant-select-selector") as HTMLElement,
  );
}

function optionsOf(): HTMLElement[] {
  return Array.from(document.querySelectorAll(".ant-select-item-option"));
}

afterEach(cleanup);

describe("ProviderSelectCard", () => {
  it("asks for the card title and the description", () => {
    const { container } = renderCard({});
    expect(container.querySelector("h3")?.textContent).toBe(
      "voiceTranscription.providerLabel",
    );
    expect(container.querySelector("h3")?.className).toBe(styles.cardTitle);
    expect(container.querySelector("p")?.textContent).toBe(
      "voiceTranscription.providerDescription",
    );
    expect(container.querySelector("p")?.className).toBe(
      styles.cardDescription,
    );
  });

  it("renders a select and no warning when providers exist", () => {
    const { container } = renderCard({ availableProviders: TWO_PROVIDERS });
    expect(selectOf(container)).not.toBeNull();
    expect(container.querySelector(".ant-alert")).toBeNull();
  });

  it("renders one provider as a select too", () => {
    const { container } = renderCard({
      availableProviders: [TWO_PROVIDERS[0]],
    });
    expect(selectOf(container)).not.toBeNull();
    expect(container.querySelector(".ant-alert")).toBeNull();
  });

  it("renders a warning and no select when there are no providers", () => {
    const { container } = renderCard({ availableProviders: [] });
    expect(selectOf(container)).toBeNull();
    const alert = container.querySelector(".ant-alert");
    expect(alert).not.toBeNull();
    expect(alert?.className).toContain("ant-alert-warning");
  });

  it("keeps the empty-state warning to a message only", () => {
    const { container } = renderCard({ availableProviders: [] });
    const alert = container.querySelector(".ant-alert");
    expect(alert?.querySelector(".ant-alert-message")?.textContent).toBe(
      "voiceTranscription.noProvidersWarning",
    );
    expect(alert?.querySelector(".ant-alert-description")).toBeNull();
  });

  it("shows an icon on the empty-state warning", () => {
    const { container } = renderCard({ availableProviders: [] });
    expect(container.querySelectorAll(".ant-alert-icon")).toHaveLength(1);
  });

  it("shows the translated placeholder while nothing is selected", () => {
    const { container } = renderCard({ selectedProviderId: "" });
    expect(
      container.querySelector(".ant-select-selection-placeholder")?.textContent,
    ).toBe("voiceTranscription.providerPlaceholder");
    expect(container.querySelector(".ant-select-selection-item")).toBeNull();
  });

  it("shows the selected provider name instead of the placeholder", () => {
    const { container } = renderCard({ selectedProviderId: "ollama" });
    const item = container.querySelector(".ant-select-selection-item");
    expect(item?.textContent).toBe("Ollama Local");
    expect(
      container.querySelector(".ant-select-selection-placeholder"),
    ).toBeNull();
  });

  it("lists one option per provider, in the order given", () => {
    const { container } = renderCard({});
    openDropdown(container);
    expect(optionsOf().map((node) => node.textContent)).toEqual([
      "OpenAI",
      "Ollama Local",
    ]);
  });

  it("keeps two same-named providers distinct by the id each one emits", () => {
    // Measured: antd renders the display NAME into both `title` and the option
    // text, so two providers sharing a name look identical in the DOM. What
    // keeps them apart is the value each click hands the parent - which is the
    // only part a user can actually observe.
    const onProviderChange = vi.fn();
    const { container } = renderCard({
      availableProviders: [
        { id: "a", name: "Same Name", available: true },
        { id: "b", name: "Same Name", available: true },
      ],
      selectedProviderId: "",
      onProviderChange,
    });
    openDropdown(container);
    const options = optionsOf();
    expect(options).toHaveLength(2);
    expect(options.map((node) => node.textContent)).toEqual([
      "Same Name",
      "Same Name",
    ]);
    expect(options.map((node) => node.getAttribute("title"))).toEqual([
      "Same Name",
      "Same Name",
    ]);

    fireEvent.click(options[0]);
    expect(onProviderChange.mock.calls[0][0]).toBe("a");
    fireEvent.click(options[1]);
    expect(onProviderChange.mock.calls[1][0]).toBe("b");
  });

  it("lists no option when there are no providers", () => {
    const { container } = renderCard({ availableProviders: [] });
    // No select is rendered at all, so the dropdown can never be opened.
    expect(container.querySelector(".ant-select-selector")).toBeNull();
    expect(optionsOf()).toHaveLength(0);
  });

  it("emits the raw provider id when an option is picked", () => {
    const onProviderChange = vi.fn();
    const { container } = renderCard({
      selectedProviderId: "openai",
      onProviderChange,
    });
    openDropdown(container);
    fireEvent.click(optionsOf()[1]);
    expect(onProviderChange).toHaveBeenCalledTimes(1);
    expect(onProviderChange.mock.calls[0][0]).toBe("ollama");
  });

  it("passes antd's option data through as the second argument", () => {
    const onProviderChange = vi.fn();
    const { container } = renderCard({
      selectedProviderId: "openai",
      onProviderChange,
    });
    openDropdown(container);
    // A different option: antd emits nothing when the current value is re-picked.
    fireEvent.click(optionsOf()[1]);
    // The product forwards `onChange` itself rather than unwrapping it, so the
    // parent sees antd's full signature (measured: `{ key, value, children }`).
    const second = onProviderChange.mock.calls[0][1] as Record<string, unknown>;
    expect(second.value).toBe("ollama");
    expect(second.children).toBe("Ollama Local");
  });

  it("emits nothing when the already-selected provider is picked again", () => {
    const onProviderChange = vi.fn();
    const { container } = renderCard({
      selectedProviderId: "openai",
      onProviderChange,
    });
    openDropdown(container);
    fireEvent.click(optionsOf()[0]);
    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("emits nothing when nothing is picked", () => {
    const onProviderChange = vi.fn();
    renderCard({ onProviderChange });
    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("is full width but capped at 400px", () => {
    const { container } = renderCard({});
    expect(selectOf(container)?.getAttribute("style")).toBe(
      "width: 100%; max-width: 400px;",
    );
  });

  it("wraps itself in the page card class", () => {
    const { container } = renderCard({});
    expect(container.querySelector(".ant-card")?.className).toContain(
      styles.card,
    );
  });
});
