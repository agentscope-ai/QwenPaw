import { PLUGIN_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";
import type { HostBundle } from "../types";

const DATAPAW_LOGO_URL =
  "https://img.alicdn.com/imgextra/i3/O1CN01pr2Xaz1GJlZiSFJrp_!!6000000000602-55-tps-519-132.svg";

let installed = false;

export function installConsoleLogoPatch(host: HostBundle): void {
  if (installed) return;
  installed = true;

  const QP = (
    window as {
      QwenPaw?: {
        slot?: {
          replace?: (
            pluginId: string,
            name: string,
            render: (defaultContent?: unknown) => unknown,
            opts?: { id?: string; order?: number },
          ) => unknown;
        };
      };
    }
  ).QwenPaw;

  if (!QP?.slot?.replace) {
    console.warn("[datapaw:logo] QwenPaw.slot.replace unavailable");
    return;
  }

  const { React } = host;

  QP.slot.replace(
    PLUGIN_ID,
    "header.logo",
    (defaultContent?: unknown) => {
      if (!isDatapawAgentSelected()) return defaultContent ?? null;
      return React.createElement("img", {
        src: DATAPAW_LOGO_URL,
        alt: "DataPaw",
        style: {
          height: 20,
          width: 79,
          objectFit: "contain",
          display: "block",
        },
      });
    },
    { id: "datapaw-header-logo", order: 10 },
  );

  console.info("[datapaw:logo] header.logo slot replacement registered");
}
