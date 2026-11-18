import { Fragment, type ReactNode } from "react";
import type { ComponentRenderProps, ElementNode } from "@openuidev/react-lang";
import { openuiLibrary } from "@openuidev/react-ui";

/** OpenUI drops unresolved array entries. Key named children by their source
 * statement so resolving an earlier sibling does not remount an existing UI.
 * Repeated references remain separate instances within each sibling list.
 */
function renderChildren(
  value: unknown,
  renderNode: ComponentRenderProps["renderNode"],
): ReactNode {
  if (!Array.isArray(value)) return renderNode(value);
  const occurrences = new Map<string, number>();
  return value.map((child) => {
    const node = child as ElementNode | null;
    const identity = JSON.stringify(
      node?.type === "element"
        ? [node.statementId ?? null, node.typeName]
        : [null, typeof child],
    );
    const occurrence = occurrences.get(identity) ?? 0;
    occurrences.set(identity, occurrence + 1);
    return (
      <Fragment key={`${identity}:${occurrence}`}>
        {renderChildren(child, renderNode)}
      </Fragment>
    );
  });
}

// Keep the official schemas, components and runtime. Only the public
// renderNode argument is adapted; wrapper types stay stable across deltas.
export const streamingLibrary = openuiLibrary.extend({
  components: {
    override: Object.values(openuiLibrary.components).map((definition) => {
      const Component = definition.component;
      function StableChildren(props: ComponentRenderProps) {
        return (
          <Component
            {...props}
            renderNode={(value) => renderChildren(value, props.renderNode)}
          />
        );
      }
      return { ...definition, component: StableChildren };
    }),
  },
});
