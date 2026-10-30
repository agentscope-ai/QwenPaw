import ConsolePollService from "../components/ConsolePollService";
import { useOsNotifyPoller } from "./useOsNotifyPoller";
import { useOsRoute } from "./osRouteStore";
import {
  buildApprovalNavigationPath,
  type ApprovalNotificationTarget,
} from "../notifications/approvalNavigation";

function openApprovals(target?: ApprovalNotificationTarget) {
  if (target?.rootSessionId?.trim()) {
    useOsRoute
      .getState()
      .openApp("core.chat", buildApprovalNavigationPath(target));
    return;
  }
  useOsRoute.getState().openApp("core.inbox", "/inbox?tab=approvals");
}

/** Desktop polling boundary: one push owner plus the inbox notification feed. */
export default function DesktopPollingServices() {
  useOsNotifyPoller();

  return <ConsolePollService onOpenApprovals={openApprovals} />;
}
