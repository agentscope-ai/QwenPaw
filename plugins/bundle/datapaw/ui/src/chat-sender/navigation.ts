import {
  navigateDataConnection,
} from "@/pages/Datapaw/DataConnection/navigation";

export {
  getDataConnectionRouteBase,
  navigateDataConnection,
} from "@/pages/Datapaw/DataConnection/navigation";

/** @deprecated Use navigateDataConnection("/add") */
export function navigateDataConnectionAdd(): void {
  navigateDataConnection("/add");
}
