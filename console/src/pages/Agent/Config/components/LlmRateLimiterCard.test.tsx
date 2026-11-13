/**
 * Unit tests for `LlmRateLimiterCard` - the LLM rate-limit tab of the Agent
 * Config page (rendered from `pages/Agent/Config/index.tsx:191`).
 *
 * What this file pins down is the card's *visible contract*: which five
 * settings it exposes, under which field names, with which lower bounds, and
 * - the non-obvious part - how the acquire-timeout validator relates to the
 * pause/jitter pair.
 *
 * Harness notes (each one is a measured fact about this target, not a guess):
 *
 * 1. A real antd `<Form>` is mandatory. The component calls
 *    `Form.useFormInstance()` and the acquire-timeout rule is an async
 *    `validator` that reads two *other* fields through that instance
 *    (`form.getFieldValue(...)`). The global stub in `src/test/design-mock.ts`
 *    exposes only `Form.Item` / `Form.useForm`, so rendering against the stub
 *    would exercise none of the validation logic. Hence the same
 *    `vi.importActual<typeof import("antd")>("antd")` swap already used by the
 *    sibling specs (`AgentLoopCard.render.test.tsx`, `ReMeLightMemoryCard.test.tsx`).
 *
 * 2. The `react-i18next` stub returns *stable* references via `vi.hoisted`.
 *    An unstable `t` would rebuild the `rules` arrays on every render and can
 *    push rc-field-form into repeated validation passes.
 *
 * 3. `t` is stubbed to return the key verbatim, so every assertion below
 *    reads the i18n key that ships in `src/locales/en.json` (verified present:
 *    `llmMaxQpmRange` at :2818, `llmRateLimitPauseMin` at :2823,
 *    `llmAcquireTimeoutGtPauseJitter` at :2834). Assertions therefore pin the
 *    *key* the product asks for, not an English sentence that could be
 *    reworded without any behaviour change.
 *
 * 4. The acquire-timeout rule is inverted relative to intuition and that is
 *    exactly why it deserves tests: the validator *passes* when
 *    `value > pause + jitter` and *throws* otherwise. Equality is a failure
 *    (`10 > 10` is false), so the timeout must be strictly greater than the
 *    pause+jitter budget. Both sides of that boundary are asserted below -
 *    testing only "it rejects" without "it accepts one unit above" would not
 *    catch an off-by-one flip.
 *
 * 5. `min` values are asserted through the rule messages the product itself
 *    declares, and the boundary value (exactly at `min`) is asserted to pass,
 *    so the assertion fails if a bound is ever tightened or loosened.
 */

import { Form } from "@agentscope-ai/design";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";

import { renderWithProviders } from "@/test/common_setup";
import { LlmRateLimiterCard } from "./LlmRateLimiterCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

// Stable stub instances (note 2 above): created once by `vi.hoisted` so every
// render sees the very same `t` and `i18n` object identity.
const i18nStub = vi.hoisted(() => ({
  t: (key: string, fallback?: string) => fallback ?? key,
  i18n: { resolvedLanguage: "en", language: "en" },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => i18nStub,
}));

/** Field names exactly as declared in the target source. */
const FIELDS = {
  maxConcurrent: "llm_max_concurrent",
  maxQpm: "llm_max_qpm",
  pause: "llm_rate_limit_pause",
  jitter: "llm_rate_limit_jitter",
  acquireTimeout: "llm_acquire_timeout",
} as const;

/**
 * Renders the card inside a real antd Form and hands the form instance out,
 * because the rules under test are driven through `form.validateFields()`.
 */
function Harness({
  onForm,
  initialValues,
}: {
  onForm?: (form: ReturnType<typeof Form.useForm>[0]) => void;
  initialValues?: Record<string, number>;
}) {
  const [form] = Form.useForm();
  useEffect(() => {
    onForm?.(form);
  }, [form, onForm]);

  return (
    <Form form={form} initialValues={initialValues}>
      <LlmRateLimiterCard />
    </Form>
  );
}

type FormInstance = ReturnType<typeof Form.useForm>[0];

/** Runs validation and normalises both outcomes into a flat message list. */
async function collectErrors(
  form: FormInstance,
  names: string[],
): Promise<string[]> {
  return form
    .validateFields(names)
    .then(() => [] as string[])
    .catch((e: { errorFields?: Array<{ errors: string[] }> }) =>
      (e.errorFields ?? []).flatMap((f) => f.errors),
    );
}

describe("LlmRateLimiterCard - exposed settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the card title and one labelled control per rate-limit setting", () => {
    renderWithProviders(<Harness />);

    // The card title is the tab's own heading, so it must be on screen.
    expect(
      screen.getByText("agentConfig.llmRateLimiterTitle"),
    ).toBeInTheDocument();

    // Each of the five settings is reachable by its translated label, which is
    // the only way a user can tell them apart.
    const labels = [
      "agentConfig.llmMaxConcurrent",
      "agentConfig.llmMaxQpm",
      "agentConfig.llmRateLimitPause",
      "agentConfig.llmRateLimitJitter",
      "agentConfig.llmAcquireTimeout",
    ];
    for (const label of labels) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("binds every control to the field name the config payload uses", () => {
    let form: FormInstance | undefined;
    renderWithProviders(<Harness onForm={(f) => (form = f)} />);

    // `initialValues` are keyed by these names in the real page, so a renamed
    // field silently stops round-tripping the user's saved config. Asserting
    // the registered names catches that.
    const registered = form!.getFieldsError().map((e) => e.name.join("."));
    expect(registered).toEqual([
      FIELDS.maxConcurrent,
      FIELDS.maxQpm,
      FIELDS.pause,
      FIELDS.jitter,
      FIELDS.acquireTimeout,
    ]);
  });

  it("accepts the value a user types into the QPM control", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(<Harness onForm={(f) => (form = f)} />);

    const qpm = screen.getByLabelText("agentConfig.llmMaxQpm");
    await act(async () => {
      fireEvent.change(qpm, { target: { value: "120" } });
    });

    // Assert the *parsed* value that lands in the config payload rather than
    // the raw DOM string: InputNumber keeps the DOM value as text while the
    // form store already holds a number, and the number is what gets saved.
    expect(form!.getFieldValue(FIELDS.maxQpm)).toBe(120);
  });

  it("does not validate on mount, so a fresh card shows no error yet", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          // 10 is *not* greater than 6 + 4, i.e. these values would fail the
          // cross-field rule - but nothing has been validated yet.
          [FIELDS.acquireTimeout]: 10,
          [FIELDS.pause]: 6,
          [FIELDS.jitter]: 4,
        }}
      />,
    );

    expect(form!.getFieldError(FIELDS.acquireTimeout)).toHaveLength(0);
    expect(await collectErrors(form!, [FIELDS.acquireTimeout])).toEqual([
      "agentConfig.llmAcquireTimeoutGtPauseJitter",
    ]);
  });
});

describe("LlmRateLimiterCard - required and lower-bound rules", () => {
  it("rejects every empty setting with its own required message", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(<Harness onForm={(f) => (form = f)} />);

    const errors = await collectErrors(form!, [
      FIELDS.maxConcurrent,
      FIELDS.maxQpm,
      FIELDS.pause,
      FIELDS.jitter,
      FIELDS.acquireTimeout,
    ]);

    // One required message per field - asserted as a set so a missing
    // `required` on any single field fails here.
    expect(errors).toEqual(
      expect.arrayContaining([
        "agentConfig.llmMaxConcurrentRequired",
        "agentConfig.llmMaxQpmRequired",
        "agentConfig.llmRateLimitPauseRequired",
        "agentConfig.llmRateLimitJitterRequired",
        "agentConfig.llmAcquireTimeoutRequired",
      ]),
    );
    expect(errors).toHaveLength(5);
  });

  it.each([
    // [field, label, below-min value, expected message]
    [
      FIELDS.maxConcurrent,
      "agentConfig.llmMaxConcurrent",
      0,
      "agentConfig.llmMaxConcurrentRange",
    ],
    [FIELDS.maxQpm, "agentConfig.llmMaxQpm", -1, "agentConfig.llmMaxQpmRange"],
    [
      FIELDS.pause,
      "agentConfig.llmRateLimitPause",
      0.5,
      "agentConfig.llmRateLimitPauseMin",
    ],
    [
      FIELDS.jitter,
      "agentConfig.llmRateLimitJitter",
      -0.5,
      "agentConfig.llmRateLimitJitterMin",
    ],
    [
      FIELDS.acquireTimeout,
      "agentConfig.llmAcquireTimeout",
      9,
      "agentConfig.llmAcquireTimeoutMin",
    ],
  ])(
    "reports the declared range message when %s is below its minimum",
    async (field, _label, value, message) => {
      let form: FormInstance | undefined;
      renderWithProviders(
        <Harness
          onForm={(f) => (form = f)}
          initialValues={{ [field]: value }}
        />,
      );

      const errors = await collectErrors(form!, [field]);

      expect(errors).toContain(message);
    },
  );

  it.each([
    [FIELDS.maxConcurrent, 1],
    [FIELDS.maxQpm, 0],
    [FIELDS.pause, 1],
    [FIELDS.jitter, 0],
  ])("accepts %s exactly at its lower bound (%p)", async (field, value) => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness onForm={(f) => (form = f)} initialValues={{ [field]: value }} />,
    );

    const errors = await collectErrors(form!, [field]);

    // The boundary itself is legal: `min` is inclusive. If a bound were ever
    // made exclusive this assertion turns red.
    expect(errors).toHaveLength(0);
  });

  it("accepts the acquire timeout exactly at its 10s floor", async () => {
    let form: FormInstance | undefined;
    // pause + jitter = 0, so 10 > 0 keeps the cross-field validator happy and
    // isolates the `min: 10.0` rule.
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 10,
          [FIELDS.pause]: 1,
          [FIELDS.jitter]: 0,
        }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    expect(errors).toHaveLength(0);
  });
});

describe("LlmRateLimiterCard - acquire timeout vs pause + jitter", () => {
  it("passes when the timeout is strictly greater than pause + jitter", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 11,
          [FIELDS.pause]: 6,
          [FIELDS.jitter]: 4,
        }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    expect(errors).toHaveLength(0);
  });

  it("fails when the timeout equals pause + jitter (the bound is strict)", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 10,
          [FIELDS.pause]: 6,
          [FIELDS.jitter]: 4,
        }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    expect(errors).toEqual(["agentConfig.llmAcquireTimeoutGtPauseJitter"]);
  });

  it("fails when the timeout is below pause + jitter", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 30,
          [FIELDS.pause]: 40,
          [FIELDS.jitter]: 5,
        }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    expect(errors).toEqual(["agentConfig.llmAcquireTimeoutGtPauseJitter"]);
  });

  it("skips the cross-field check while pause is still unset", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{ [FIELDS.acquireTimeout]: 15, [FIELDS.jitter]: 2 }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    // The validator bails out when a dependency is not a number yet, so a
    // half-filled form must not show the "greater than" complaint.
    expect(errors).not.toContain("agentConfig.llmAcquireTimeoutGtPauseJitter");
    expect(errors).toHaveLength(0);
  });

  it("skips the cross-field check while jitter is still unset", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{ [FIELDS.acquireTimeout]: 15, [FIELDS.pause]: 2 }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    expect(errors).not.toContain("agentConfig.llmAcquireTimeoutGtPauseJitter");
    expect(errors).toHaveLength(0);
  });

  it("reports only the required message when the timeout itself is empty", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{ [FIELDS.pause]: 60, [FIELDS.jitter]: 30 }}
      />,
    );

    const errors = await collectErrors(form!, [FIELDS.acquireTimeout]);

    // `typeof value !== "number"` short-circuits the validator, so an empty
    // timeout must yield the required message and *not* the cross-field one.
    expect(errors).toEqual(["agentConfig.llmAcquireTimeoutRequired"]);
  });
});

describe("LlmRateLimiterCard - dependency wiring", () => {
  it("re-validates the timeout when pause grows past it", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 11,
          [FIELDS.pause]: 6,
          [FIELDS.jitter]: 4,
        }}
      />,
    );

    // Starts clean: 11 > 6 + 4.
    expect(await collectErrors(form!, [FIELDS.acquireTimeout])).toHaveLength(0);

    const pause = screen.getByLabelText("agentConfig.llmRateLimitPause");
    await act(async () => {
      fireEvent.change(pause, { target: { value: "20" } });
    });

    // `dependencies` must pull the timeout back into validation on its own -
    // without an explicit validateFields call - otherwise the stale value
    // would stay invisible until submit.
    await waitFor(() => {
      const errs = form!.getFieldError(FIELDS.acquireTimeout);
      expect(errs).toContain("agentConfig.llmAcquireTimeoutGtPauseJitter");
    });
  });

  it("re-validates the timeout when jitter grows past it", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 12,
          [FIELDS.pause]: 5,
          [FIELDS.jitter]: 5,
        }}
      />,
    );

    expect(await collectErrors(form!, [FIELDS.acquireTimeout])).toHaveLength(0);

    const jitter = screen.getByLabelText("agentConfig.llmRateLimitJitter");
    await act(async () => {
      fireEvent.change(jitter, { target: { value: "9" } });
    });

    await waitFor(() => {
      expect(form!.getFieldError(FIELDS.acquireTimeout)).toContain(
        "agentConfig.llmAcquireTimeoutGtPauseJitter",
      );
    });
  });

  it("clears the cross-field error once the timeout is raised above the new budget", async () => {
    let form: FormInstance | undefined;
    renderWithProviders(
      <Harness
        onForm={(f) => (form = f)}
        initialValues={{
          [FIELDS.acquireTimeout]: 11,
          [FIELDS.pause]: 6,
          [FIELDS.jitter]: 4,
        }}
      />,
    );

    // Step 1: grow pause so the budget overtakes the timeout. The dependency
    // wiring surfaces the error without an explicit validateFields call.
    const pause = screen.getByLabelText("agentConfig.llmRateLimitPause");
    await act(async () => {
      fireEvent.change(pause, { target: { value: "20" } });
    });
    await waitFor(() => {
      expect(form!.getFieldError(FIELDS.acquireTimeout)).toContain(
        "agentConfig.llmAcquireTimeoutGtPauseJitter",
      );
    });

    // Step 2: the user fixes it by raising the timeout above the new budget.
    // The error must disappear on its own, otherwise the card would keep a
    // stale complaint after the value became legal again.
    const timeout = screen.getByLabelText("agentConfig.llmAcquireTimeout");
    await act(async () => {
      fireEvent.change(timeout, { target: { value: "25" } });
    });

    await waitFor(() => {
      expect(form!.getFieldError(FIELDS.acquireTimeout)).toHaveLength(0);
    });
  });
});
