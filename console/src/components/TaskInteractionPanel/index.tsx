import React from "react";
import ChatPlanPanel from "../ChatPlanPanel";
import RuntimeStatusPanel from "../RuntimeStatusPanel";
import UserInputPanel from "../UserInputPanel";
import { usePendingUserInput } from "../UserInputPanel/usePendingUserInput";

interface TaskInteractionPanelProps {
  planEnabled: boolean;
}

const TaskInteractionPanel: React.FC<TaskInteractionPanelProps> = ({
  planEnabled,
}) => {
  const { request, refresh } = usePendingUserInput(true);

  if (request) {
    return <UserInputPanel request={request} onResolved={refresh} />;
  }

  return (
    <>
      <RuntimeStatusPanel enabled />
      <ChatPlanPanel enabled={planEnabled} />
    </>
  );
};

export default TaskInteractionPanel;
