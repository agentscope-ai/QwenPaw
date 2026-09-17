import { Result } from "antd";
import type { ReactNode } from "react";
import { useAuthStore } from "../stores/authStore";
import { can } from "./capabilities";

export default function CapabilityBoundary({
  capability,
  children,
}: {
  capability?: string;
  children: ReactNode;
}) {
  const mode = useAuthStore((state) => state.mode);
  const role = useAuthStore((state) => state.user?.platform_role ?? null);

  if (capability && !can(mode, role, capability)) {
    return <Result status="403" title="403" subTitle="无权访问" />;
  }
  return <>{children}</>;
}
