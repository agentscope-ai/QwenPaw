import { RouterProvider } from "react-router-dom";
import { creatorRouter } from "@/app/router";

export default function App() {
  return <RouterProvider router={creatorRouter} />;
}
