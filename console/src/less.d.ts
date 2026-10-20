/**
 * Ambient declaration for the `less` devDependency used by stylesheet
 * unit tests. Kept in a global script file (no top-level import/export)
 * so TypeScript treats it as an ambient module declaration.
 */
declare module "less" {
  interface LessRenderResult {
    css: string;
  }

  interface LessRenderOptions {
    filename?: string;
    paths?: string[];
  }

  const less: {
    render: (
      input: string,
      options?: LessRenderOptions,
    ) => Promise<LessRenderResult>;
  };
  export default less;
}
