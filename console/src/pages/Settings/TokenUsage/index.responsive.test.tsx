import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DatePicker } from "antd";
import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
import styles from "./index.module.less";

describe("TokenUsage mobile range picker", () => {
  it("targets the real AntD preset layout with its route-local popup", async () => {
    const user = userEvent.setup();
    render(
      <DatePicker.RangePicker
        classNames={{ popup: { root: styles.mobileRangePopup } }}
        presets={[
          {
            label: "Last 30 days",
            value: [dayjs().subtract(29, "day"), dayjs()],
          },
        ]}
      />,
    );

    await user.click(screen.getAllByRole("textbox")[0]);

    const popup = document.querySelector(`.${styles.mobileRangePopup}`);
    expect(popup).not.toBeNull();
    expect(
      popup?.querySelector(
        ".ant-picker-panel-container " +
          ".ant-picker-panel-layout > .ant-picker-presets",
      ),
    ).not.toBeNull();
    expect(
      popup?.querySelectorAll(".ant-picker-panels > .ant-picker-panel"),
    ).toHaveLength(2);
  });
});
