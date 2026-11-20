import {
  createElement,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  getAgentAccessScopeKey,
  subscribeChatSessionScope,
} from "../../stores/chatSessionScope";
import { pluginInput, type PluginNode } from "./protocol";
import type { PluginWorkerClient } from "./workerClient";
import { PluginFileAction } from "./PluginFileAction";
import i18n from "i18next";

function onLocaleChange(listener: () => void) {
  i18n.on("languageChanged", listener);
  return () => {
    i18n.off("languageChanged", listener);
  };
}

function nodeView(
  node: PluginNode,
  act: (action: string, value?: string) => void,
  pluginId: string,
  key = "root",
): React.ReactNode {
  if (node === null || typeof node === "string") return node;
  const children = node.children?.map((child, index) =>
    nodeView(child, act, pluginId, `${key}.${index}`),
  );
  if (node.tag === "file-action")
    return (
      <PluginFileAction
        key={`${key}:${node.path}`}
        node={node}
        pluginId={pluginId}
        afterUpload={() => act(node.action || "refresh")}
      />
    );
  if (node.tag === "input")
    return createElement("input", {
      key,
      value: node.value ?? "",
      placeholder: node.placeholder,
      disabled: node.disabled,
      onChange: node.action
        ? (event: React.ChangeEvent<HTMLInputElement>) =>
            act(node.action!, event.target.value)
        : undefined,
      readOnly: !node.action,
    });
  return createElement(
    node.tag,
    {
      key,
      ...(node.tag === "button"
        ? {
            type: "button",
            disabled: node.disabled,
            onClick: node.action ? () => act(node.action!) : undefined,
          }
        : {}),
    },
    node.text,
    children,
  );
}

export function PluginView({
  client,
  target,
  input,
}: {
  client: PluginWorkerClient;
  target: string;
  input: unknown;
}) {
  const scope = useSyncExternalStore(
    subscribeChatSessionScope,
    getAgentAccessScopeKey,
  );
  const stopped = useSyncExternalStore(
    client.subscribeStopped,
    client.getStopped,
  );
  const locale = useSyncExternalStore(
    onLocaleChange,
    () => i18n.language || navigator.language,
  );
  const serialized = JSON.stringify(pluginInput(input));
  const [state, setState] = useState<{
    scope: string;
    view: PluginNode;
    error: boolean;
    loaded: boolean;
  }>({ scope, view: null, error: false, loaded: false });
  const revision = useRef(0);
  const mounted = useRef(true);
  const render = (action?: string, value?: string) => {
    const current = ++revision.current;
    void client
      .render(
        target,
        JSON.parse(serialized),
        action ? { action, value } : undefined,
      )
      .then((view) => {
        if (
          mounted.current &&
          current === revision.current &&
          scope === getAgentAccessScopeKey()
        )
          setState({ scope, view, error: false, loaded: true });
      })
      .catch(() => {
        if (mounted.current && current === revision.current)
          setState({ scope, view: null, error: true, loaded: true });
      });
  };
  useEffect(() => {
    mounted.current = true;
    render();
    return () => {
      mounted.current = false;
    };
    // The serialized props are intentionally the dependency; callback props are omitted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, target, serialized, scope, locale]);
  if (stopped) return null;
  if (state.scope !== scope || !state.loaded)
    return <span role="status">正在加载插件…</span>;
  if (state.error)
    return <div role="alert">插件已停止响应，刷新页面可重新加载。</div>;
  return (
    <section aria-label="插件内容">
      {nodeView(state.view, render, client.pluginId)}
    </section>
  );
}
