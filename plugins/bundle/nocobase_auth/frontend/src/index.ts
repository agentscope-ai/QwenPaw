/**
 * NocoBase auth frontend plugin entry point.
 */

import { ConfigPage } from "./pages/ConfigPage";
import { UsersPage } from "./pages/UsersPage";
import { RolesPage } from "./pages/RolesPage";

function register() {
  const QwenPaw = (window as any).QwenPaw;
  if (!QwenPaw?.registerRoutes) {
    console.warn("[nocobase-auth] QwenPaw.registerRoutes not available");
    return;
  }

  QwenPaw.registerRoutes("nocobase-auth", [
    {
      path: "/nocobase-auth/config",
      component: ConfigPage,
      label: "NocoBase Auth",
      icon: "🔐",
      priority: 10,
    },
    {
      path: "/nocobase-auth/users",
      component: UsersPage,
      label: "NocoBase 用户",
      icon: "👤",
      priority: 11,
    },
    {
      path: "/nocobase-auth/roles",
      component: RolesPage,
      label: "角色映射",
      icon: "🛡️",
      priority: 12,
    },
  ]);
}

register();
