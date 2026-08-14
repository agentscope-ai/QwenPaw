import { Button, Empty, Spin } from "antd";
import { AppWindow, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PawAppRuntime } from "./usePawAppRuntime";

interface PawAppLoadStateProps {
  className: string;
  runtime: PawAppRuntime;
}

/** Shared loading and retry state for embedded PawApp surfaces. */
export function PawAppLoadState({ className, runtime }: PawAppLoadStateProps) {
  const { t } = useTranslation();

  if (runtime.state === "loading") {
    return (
      <div className={className}>
        <Spin tip={t("appCenter.loadingApp")} />
      </div>
    );
  }

  return (
    <div className={className}>
      <Empty
        image={<AppWindow size={44} strokeWidth={1} />}
        description={t("appCenter.appLoadFailed")}
      >
        <Button
          type="primary"
          icon={<RefreshCw size={14} />}
          onClick={runtime.retry}
        >
          {t("common.retry")}
        </Button>
      </Empty>
    </div>
  );
}
