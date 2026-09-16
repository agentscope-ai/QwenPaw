import { host, qwenpaw } from "./host";
import { RecordingSurface } from "./surface";

const React = host.React;
qwenpaw.chat.rightHeader.add("record-and-replay", <RecordingSurface />, {
  id: "recording-controls",
  order: 60,
});
qwenpaw.route.add("record-and-replay", {
  id: "record-and-replay.settings",
  path: "/plugin/record-and-replay",
  component: () => <RecordingSurface page />,
});
qwenpaw.menu.add("record-and-replay", {
  id: "record-and-replay.settings",
  location: "primary.settings",
  label: "Record & Replay",
  icon: <span>⏺</span>,
  route: "record-and-replay.settings",
  order: 44,
});
