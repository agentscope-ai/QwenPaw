import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { creatorRouter } from "@/app/router";
import {
  CreatorBackendBlockingOverlay,
  CreatorBackendNotReadyPage,
} from "@/components/system/CreatorBackendStatus";
import { useCreatorBackendHealthStore } from "@/store/creatorBackendHealthStore";

export default function App() {
  const phase = useCreatorBackendHealthStore((state) => state.phase);
  const everReady = useCreatorBackendHealthStore((state) => state.everReady);

  useEffect(() => {
    // 启动即探测：后端未加载时宿主 SPA catch-all 只回 405，提前拦截能
    // 把 "Method Not Allowed" 换成可行动的排查指引。
    void useCreatorBackendHealthStore.getState().check();
  }, []);

  if (phase === "unavailable" && !everReady) {
    return <CreatorBackendNotReadyPage />;
  }

  return (
    <>
      <RouterProvider router={creatorRouter} />
      <CreatorBackendBlockingOverlay />
    </>
  );
}
