import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FormInstance } from "antd";
import { RuleModal } from "./RuleModal";

const selectProps = vi.hoisted(
  () =>
    [] as Array<{
      mode?: string;
      options?: Array<{ label: string; value: string }>;
    }>,
);

vi.mock("@agentscope-ai/design", () => {
  const PassThrough = ({ children }: { children?: ReactNode }) => (
    <div>{children}</div>
  );
  const Input = Object.assign(PassThrough, { TextArea: PassThrough });
  const Select = (props: (typeof selectProps)[number]) => {
    selectProps.push(props);
    return <div />;
  };

  return {
    Form: PassThrough,
    Input,
    Modal: PassThrough,
    Select,
  };
});

vi.mock("@/components/interaction/SettingsField", () => ({
  SettingsField: ({ children }: { children?: ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("RuleModal", () => {
  beforeEach(() => {
    selectProps.length = 0;
  });

  it("exposes each target tool option exactly once", () => {
    const form = {
      resetFields: vi.fn(),
      setFieldsValue: vi.fn(),
    } as unknown as FormInstance;

    render(
      <RuleModal
        open
        editingRule={null}
        existingRuleIds={[]}
        onOk={vi.fn()}
        onCancel={vi.fn()}
        form={form}
      />,
    );

    const toolSelect = selectProps.find(
      ({ mode, options }) => mode === "tags" && options !== undefined,
    );
    const values = toolSelect?.options?.map((option) => option.value) ?? [];
    const labels = toolSelect?.options?.map((option) => option.label) ?? [];

    expect(new Set(values).size).toBe(values.length);
    expect(new Set(labels).size).toBe(labels.length);
    expect(values.filter((value) => value === "browser")).toHaveLength(1);
  });
});
