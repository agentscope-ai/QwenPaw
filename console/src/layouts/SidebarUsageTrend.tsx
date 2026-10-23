import { memo } from "react";
import { SnapTrend } from "../components/interaction/SnapTrend";

/** Lazy sidebar detail boundary: instantiate the chart only when opened. */
function SidebarUsageTrend({
  points,
  label,
  mobile,
}: {
  points: { date: string; value: number; model: string }[];
  label: string;
  mobile: boolean;
}) {
  return (
    <SnapTrend
      label={label}
      compact
      config={{
        data: points,
        xField: "date",
        yField: "value",
        colorField: "model",
        height: mobile ? 190 : 230,
        axis: {
          x: {
            title: false,
            labelFormatter: (value: string) => value.slice(5).replace("-", "/"),
            labelAutoRotate: false,
            tick: false,
            line: false,
          },
          y: false,
        },
        legend: false,
        style: { lineWidth: 2.5 },
        animate: false,
      }}
    />
  );
}

export default memo(SidebarUsageTrend);
