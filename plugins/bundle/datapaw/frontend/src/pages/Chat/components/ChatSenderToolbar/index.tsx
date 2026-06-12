import type { FC } from "react";
import DataSourceSelector from "./DataSourceSelector";
import PlanModeSelector from "./PlanModeSelector";
import styles from "./index.module.less";

const ChatSenderToolbar: FC = () => {
  return (
    <div className={styles.toolbar}>
      <DataSourceSelector />
      {/* <PlanModeSelector /> */}
    </div>
  );
};

export default ChatSenderToolbar;
