type HostUiDependencies = {
  antd: typeof import("antd");
  antdIcons: typeof import("@ant-design/icons");
};

let dependencies: HostUiDependencies | undefined;
let pending: Promise<void> | undefined;

/** Prepare complete namespaces before evaluating any external plugin. */
export function loadHostUiDependencies(): Promise<void> {
  pending ??= Promise.all([import("antd"), import("@ant-design/icons")])
    .then(([antd, antdIcons]) => {
      dependencies = { antd, antdIcons };
    })
    .catch((error: unknown) => {
      pending = undefined;
      throw error;
    });
  return pending;
}

/** Keep the legacy synchronous host API after the loader's async boundary. */
export function getHostUiDependencies(): HostUiDependencies {
  if (!dependencies) {
    throw new Error(
      "Host UI dependencies must be loaded before executing a plugin.",
    );
  }
  return dependencies;
}
