import { Form } from "@agentscope-ai/design";
import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import React from "react";

import { renderWithProviders } from "@/test/common_setup";
import { ProactiveAgendaCard } from "./ProactiveAgendaCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "zh-CN", language: "zh-CN" },
  }),
}));

function ProactiveForm({
  proactiveEnabled = false,
  proactiveCronEnabled = false,
  formRef,
}: {
  proactiveEnabled?: boolean;
  proactiveCronEnabled?: boolean;
  formRef?: React.MutableRefObject<ReturnType<typeof Form.useForm>[0] | null>;
}) {
  const [form] = Form.useForm();
  if (formRef) {
    formRef.current = form;
  }
  return (
    <Form
      form={form}
      initialValues={{
        reme_light_memory_config: {
          proactive_enabled: proactiveEnabled,
          proactive_cron_enabled: proactiveCronEnabled,
          proactive_cron: "30 8 * * *",
          proactive_inbox_push_enabled: true,
          proactive_max_items: 3,
          proactive_cron_max_items: 0,
          proactive_delivery_cooldown_days: 3,
          proactive_refresh_min_interval_minutes: 120,
        },
      }}
    >
      <ProactiveAgendaCard />
    </Form>
  );
}

describe("proactive agenda", () => {
  const rowControl = (element: HTMLElement, selector: string) =>
    element.parentElement?.parentElement?.querySelector(
      selector,
    ) as HTMLElement;
  const proactiveSwitch = (label: string) =>
    rowControl(screen.getByText(label), '[role="switch"]');
  const proactiveNumber = (label: string) =>
    rowControl(screen.getByText(label), '[role="spinbutton"]');

  it("keeps every proactive control off and disabled by default", () => {
    renderWithProviders(<ProactiveForm />);

    expect(
      screen.getByText("agentConfig.proactiveSectionTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("switch", {
        name: "agentConfig.proactiveEnableTitle",
      }),
    ).toHaveAttribute("aria-checked", "false");

    expect(proactiveNumber("agentConfig.proactiveMaxItems")).toBeDisabled();
    expect(
      proactiveNumber("agentConfig.proactiveRefreshInterval"),
    ).toBeDisabled();
    expect(proactiveNumber("agentConfig.proactiveCooldownDays")).toBeDisabled();
    expect(proactiveNumber("agentConfig.proactiveCronMaxItems")).toBeDisabled();
    expect(proactiveSwitch("agentConfig.proactiveNotifyTitle")).toBeDisabled();
    expect(proactiveSwitch("agentConfig.proactiveCronTitle")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "cronJobs.cronTime: 08:30" }),
    ).toBeDisabled();
  });

  it("enables the round controls but not the daily push by default", () => {
    renderWithProviders(<ProactiveForm proactiveEnabled />);

    expect(
      screen.getByRole("switch", {
        name: "agentConfig.proactiveEnableTitle",
      }),
    ).toHaveAttribute("aria-checked", "true");

    const maxItems = proactiveNumber("agentConfig.proactiveMaxItems");
    expect(maxItems).toBeEnabled();
    expect(maxItems).toHaveDisplayValue("3");
    expect(
      proactiveNumber("agentConfig.proactiveCooldownDays"),
    ).toHaveDisplayValue("3");
    expect(
      proactiveNumber("agentConfig.proactiveRefreshInterval"),
    ).toHaveDisplayValue("120");
    expect(proactiveSwitch("agentConfig.proactiveNotifyTitle")).toBeEnabled();
    expect(proactiveSwitch("agentConfig.proactiveNotifyTitle")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    // The daily push stays gated behind its own switch.
    expect(proactiveSwitch("agentConfig.proactiveCronTitle")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(
      screen.getByRole("button", { name: "cronJobs.cronTime: 08:30" }),
    ).toBeDisabled();
    expect(proactiveNumber("agentConfig.proactiveCronMaxItems")).toBeDisabled();
  });

  it("enables the daily push schedule with its own switch", () => {
    renderWithProviders(
      <ProactiveForm proactiveEnabled proactiveCronEnabled />,
    );

    expect(
      screen.getByRole("button", { name: "cronJobs.cronTime: 08:30" }),
    ).toBeEnabled();
    const cronItems = proactiveNumber("agentConfig.proactiveCronMaxItems");
    expect(cronItems).toBeEnabled();
    expect(cronItems).toHaveDisplayValue("0");
  });

  it("rejects a cleared number instead of submitting null", async () => {
    const formRef = {
      current: null as ReturnType<typeof Form.useForm>[0] | null,
    };
    renderWithProviders(<ProactiveForm proactiveEnabled formRef={formRef} />);
    const form = formRef.current!;

    // InputNumber commits an emptied box as null, which the backend schema
    // rejects even while the section is disabled, so validation must catch it.
    await act(async () => {
      fireEvent.change(proactiveNumber("agentConfig.proactiveMaxItems"), {
        target: { value: "" },
      });
    });

    const errors = await act(async () => {
      return await form
        .validateFields()
        .then(() => [])
        .catch((e) => e.errorFields ?? []);
    });
    expect(errors.map((e: { name: string[] }) => e.name.join("."))).toContain(
      "reme_light_memory_config.proactive_max_items",
    );
    expect(
      screen.getAllByText("agentConfig.proactiveNumberRequired").length,
    ).toBeGreaterThan(0);
  });

  it("restores the defaults when the section is switched off", async () => {
    renderWithProviders(
      <ProactiveForm proactiveEnabled proactiveCronEnabled />,
    );

    for (const label of [
      "agentConfig.proactiveMaxItems",
      "agentConfig.proactiveRefreshInterval",
      "agentConfig.proactiveCooldownDays",
      "agentConfig.proactiveCronMaxItems",
    ]) {
      await act(async () => {
        fireEvent.change(proactiveNumber(label), { target: { value: "" } });
      });
    }

    await act(async () => {
      fireEvent.click(
        screen.getByRole("switch", {
          name: "agentConfig.proactiveEnableTitle",
        }),
      );
    });

    expect(proactiveNumber("agentConfig.proactiveMaxItems")).toHaveDisplayValue(
      "3",
    );
    expect(
      proactiveNumber("agentConfig.proactiveRefreshInterval"),
    ).toHaveDisplayValue("120");
    expect(
      proactiveNumber("agentConfig.proactiveCooldownDays"),
    ).toHaveDisplayValue("3");
    expect(
      proactiveNumber("agentConfig.proactiveCronMaxItems"),
    ).toHaveDisplayValue("0");
  });

  it("restores the push count when only the daily push is switched off", async () => {
    renderWithProviders(
      <ProactiveForm proactiveEnabled proactiveCronEnabled />,
    );

    await act(async () => {
      fireEvent.change(proactiveNumber("agentConfig.proactiveCronMaxItems"), {
        target: { value: "" },
      });
    });
    await act(async () => {
      fireEvent.click(proactiveSwitch("agentConfig.proactiveCronTitle"));
    });

    expect(
      proactiveNumber("agentConfig.proactiveCronMaxItems"),
    ).toHaveDisplayValue("0");
    // The round controls keep whatever the user entered.
    expect(proactiveNumber("agentConfig.proactiveMaxItems")).toHaveDisplayValue(
      "3",
    );
  });
});
