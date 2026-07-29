import {
  Navigate,
  Outlet,
  createHashRouter,
  type RouteObject,
} from "react-router-dom";
import { Suspense, lazy } from "react";
import ProjectLayout from "@/components/layout/ProjectLayout";
import PageSkeleton from "@/components/PageSkeleton";
import { loadWithChunkRecovery } from "@/lib/lazyWithChunkRecovery";
import { NavigationRuntime, navigate, useParams } from "@/routing/navigation";

const HomePage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/HomePage")),
);
const PlanPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/PlanPage")),
);
const AssetsPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/AssetsPage")),
);
const R2VWorkbenchPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/R2VWorkbenchPage")),
);

function suspended(
  element: React.ReactNode,
  type: "grid" | "list" | "editor" = "list",
) {
  return <Suspense fallback={<PageSkeleton type={type} />}>{element}</Suspense>;
}

export const FORMAL_CREATOR_ROUTES = [
  "/",
  "/project/:id/plan",
  "/project/:id/plan/element/:elementId",
  "/project/:id/assets",
] as const;

function RouteRuntime() {
  return (
    <>
      <NavigationRuntime />
      <Outlet />
    </>
  );
}

export function NotFoundPage({ projectId }: { projectId?: string }) {
  return (
    <div className="flex h-full min-h-[60vh] items-center justify-center bg-[var(--color-bg-layout)] px-6">
      <div className="max-w-sm text-center">
        <p className="text-sm font-semibold text-[var(--color-text-primary)]">
          页面未找到
        </p>
        <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
          当前地址没有对应的 Creator 页面。
        </p>
        <button
          type="button"
          onClick={() =>
            navigate(projectId ? `/project/${projectId}/plan` : "/", true)
          }
          className="mt-4 rounded border border-[var(--color-border)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)]"
        >
          返回
        </button>
      </div>
    </div>
  );
}

function ProjectNotFoundPage() {
  const { id } = useParams();
  return <NotFoundPage projectId={id} />;
}

export const CREATOR_ROUTE_OBJECTS: RouteObject[] = [
  {
    id: "route-runtime",
    element: <RouteRuntime />,
    children: [
      { id: "home", path: "/", element: suspended(<HomePage />, "grid") },
      {
        id: "project",
        path: "/project/:id",
        element: <ProjectLayout />,
        children: [
          {
            id: "project-default",
            index: true,
            element: <Navigate to="plan" replace />,
          },
          {
            id: "project-plan",
            path: "plan",
            element: suspended(<PlanPage />),
          },
          {
            id: "project-element-workbench",
            path: "plan/element/:elementId",
            element: suspended(<R2VWorkbenchPage />, "editor"),
          },
          {
            id: "project-assets",
            path: "assets",
            element: suspended(<AssetsPage />, "grid"),
          },
          {
            id: "project-not-found",
            path: "*",
            element: <ProjectNotFoundPage />,
          },
        ],
      },
      { id: "not-found", path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createCreatorRouter() {
  return createHashRouter(CREATOR_ROUTE_OBJECTS);
}

export const creatorRouter = createCreatorRouter();
