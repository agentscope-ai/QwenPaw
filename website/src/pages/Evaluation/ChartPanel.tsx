import { useEffect, useState, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import type Chart from "./Chart";

type ChartComponent = typeof Chart;

export default function ChartPanel(props: ComponentProps<ChartComponent>) {
  const { t } = useTranslation("evaluation");
  const [component, setComponent] = useState<ChartComponent | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setFailed(false);
    const timer = window.setTimeout(() => {
      active = false;
      setFailed(true);
    }, 20000);
    void import("./Chart").then(
      (module) => {
        if (active) {
          window.clearTimeout(timer);
          setComponent(() => module.default);
        }
      },
      () => {
        if (active) {
          window.clearTimeout(timer);
          setFailed(true);
        }
      },
    );
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [attempt]);
  const LoadedChart = component;
  if (LoadedChart) return <LoadedChart {...props} />;
  return (
    <div className="evaluation-plot evaluation-chart-loading" role="status">
      <p>{t(failed ? "chartUnavailable" : "chartLoading")}</p>
      {failed && (
        <button onClick={() => setAttempt((value) => value + 1)}>
          <RefreshCw size={16} />
          {t("retry")}
        </button>
      )}
    </div>
  );
}
