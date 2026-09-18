/**
 * Extension → Monaco language id mapping for the Coding editor.
 * Shared by the normal editor and the DiffEditor in TabbedEditor.
 */

export function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    sh: "shell",
    bash: "shell",
    html: "html",
    css: "css",
    less: "less",
    scss: "scss",
    sql: "sql",
    toml: "ini",
    rs: "rust",
    go: "go",
    java: "java",
    cs: "csharp",
    cpp: "cpp",
    cc: "cpp",
    cxx: "cpp",
    c: "c",
    h: "c",
    hpp: "cpp",
    hh: "cpp",
    hxx: "cpp",
    kt: "kotlin",
    rb: "ruby",
    robot: "robotframework",
    resource: "robotframework",
    // Monaco does not ship dedicated ShaderLab/HLSL/GLSL/GDScript tokenizers;
    // these close built-in grammars still provide useful syntax highlighting.
    shader: "cpp",
    cginc: "cpp",
    hlsl: "cpp",
    gdshader: "cpp",
    glsl: "cpp",
    vert: "cpp",
    frag: "cpp",
    wgsl: "wgsl",
    gd: "python",
  };
  return map[ext] ?? "plaintext";
}
