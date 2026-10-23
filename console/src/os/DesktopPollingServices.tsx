import ConsolePollService from "../components/ConsolePollService";
import { useOsNotifyPoller } from "./useOsNotifyPoller";

/** Desktop polling boundary: one push owner plus the inbox notification feed. */
export default function DesktopPollingServices() {
  useOsNotifyPoller();

  return <ConsolePollService />;
}
