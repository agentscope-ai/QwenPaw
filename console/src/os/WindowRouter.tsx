/**
 * WindowRouter.tsx — Per-window router sandbox for the Desktop OS.
 *
 * Wraps a page component in its own MemoryRouter seeded at the app's base path
 * so shared components keep using useNavigate / useLocation / useParams exactly
 * as they do in the browser — but scoped to this window instead of the global
 * URL. A bridge translates two things:
 *   - Deep-link IN: an external target (osRouteStore) navigates this window's
 *     local router (e.g. opening a specific chat session).
 *   - Cross-app OUT: navigation to a path owned by ANOTHER app opens/focuses
 *     that app's window (via osRouteStore) and restores this window to its last
 *     own-app location, so its state (e.g. current session) is preserved.
 *
 * The browser layout (MainLayout) is untouched — it keeps the top BrowserRouter.
 */
import { useEffect, useRef, type ReactNode } from "react";
import {
  MemoryRouter,
  Routes,
  Route,
  Navigate,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useRoutes } from "../plugins/registry/hooks";
import { useOsRoute } from "./osRouteStore";
import { pathToRouteId } from "./osRouteMap";

interface WindowRouterProps {
  /** This window's route id (e.g. "core.chat"). */
  routeId: string;
  /** Router base path for this app (e.g. "/chat"). */
  base: string;
  /** The page component element to render. */
  element: ReactNode;
}

function WindowRouterBridge({
  routeId,
  base,
}: {
  routeId: string;
  base: string;
}) {
  const routes = useRoutes();
  const navigate = useNavigate();
  const location = useLocation();
  const target = useOsRoute((s) => s.targets[routeId]);
  const navigateTo = useOsRoute((s) => s.navigateTo);

  const lastOwnPath = useRef(base);
  // Start at 0 so a target already pending when the window opens still fires.
  const seenNonce = useRef(0);

  // Deep-link IN: external target -> navigate this window's local router.
  useEffect(() => {
    if (target && target.nonce !== seenNonce.current) {
      seenNonce.current = target.nonce;
      navigate(target.path);
    }
  }, [target, navigate]);

  // Cross-app OUT: navigation to another app's path -> open that app window.
  useEffect(() => {
    const targetId = pathToRouteId(location.pathname, routes);
    if (!targetId || targetId === routeId) {
      // Intra-app navigation — remember it so we can restore after a bounce.
      lastOwnPath.current = location.pathname + location.search;
      return;
    }
    navigateTo(targetId, location.pathname + location.search);
    // Restore this window to its last own-app location (preserve state).
    navigate(lastOwnPath.current, { replace: true });
  }, [location, routeId, routes, navigate, navigateTo]);

  return null;
}

export default function WindowRouter({
  routeId,
  base,
  element,
}: WindowRouterProps) {
  return (
    <MemoryRouter initialEntries={[base]}>
      <WindowRouterBridge routeId={routeId} base={base} />
      <Routes>
        <Route path={`${base}/*`} element={element} />
        <Route path="*" element={<Navigate to={base} replace />} />
      </Routes>
    </MemoryRouter>
  );
}
