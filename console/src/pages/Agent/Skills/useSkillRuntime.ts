import { useEffect, useMemo, useRef } from "react";
import type { ModalFuncProps } from "antd";
import rootApi from "@/api";
import { createSkillApi } from "@/api/modules/skill";
import { useSkillScope, type SkillScope } from "@/api/skillScope";
import { useAppMessage } from "@/hooks/useAppMessage";

export function useSkillRuntime(agentId?: string) {
  const scope = useSkillScope(agentId);
  const { message: appMessage, modal: appModal } = useAppMessage();
  const confirmations = useRef(new Set<() => void>());
  useEffect(() => {
    const cancel = () => {
      confirmations.current.forEach((close) => close());
      confirmations.current.clear();
    };
    scope.signal.addEventListener("abort", cancel);
    return () => {
      scope.signal.removeEventListener("abort", cancel);
      cancel();
    };
  }, [scope]);
  const api = useMemo(
    () => ({ ...rootApi, ...createSkillApi(scope) }),
    [scope],
  );
  const message = useMemo(
    () =>
      new Proxy(appMessage, {
        get:
          (target, name: keyof typeof appMessage) =>
          (...args: unknown[]) => {
            if (scope.current())
              return (target[name] as (...args: unknown[]) => unknown)(...args);
          },
      }) as typeof appMessage,
    [appMessage, scope],
  );
  const modal = useMemo(
    () => ({
      confirm: (options: ModalFuncProps) => {
        if (!scope.current()) {
          options.onCancel?.();
          return;
        }
        const close = () => {
          instance.destroy();
          options.onCancel?.();
          confirmations.current.delete(close);
        };
        const instance = appModal.confirm({
          ...options,
          onOk: async () => {
            confirmations.current.delete(close);
            if (scope.current()) return options.onOk?.();
          },
          onCancel: () => {
            confirmations.current.delete(close);
            options.onCancel?.();
          },
        });
        confirmations.current.add(close);
        return instance;
      },
    }),
    [appModal, scope],
  );
  return { scope, api, message, modal };
}

export function skillErrorMessage(error: unknown, t: (key: string) => string) {
  const text = error instanceof Error ? error.message : "";
  if (/forbidden|not_authorized/.test(text))
    return t("skillGovernance.forbidden");
  if (
    /content_conflict|skill_conflict|skill_source_changed|skill_version_changed|version_conflict/.test(
      text,
    )
  )
    return t("skillGovernance.conflict");
  if (/postgres_governance_required/.test(text))
    return t("skillGovernance.unavailableLegacy");
  return t("skillGovernance.failed");
}

export async function confirmSkillAction(
  scope: SkillScope,
  modal: ReturnType<typeof useSkillRuntime>["modal"],
  options: ModalFuncProps,
) {
  if (!scope.current()) return false;
  const accepted = await new Promise<boolean>((resolve) =>
    modal.confirm({
      ...options,
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    }),
  );
  return accepted && scope.current();
}
