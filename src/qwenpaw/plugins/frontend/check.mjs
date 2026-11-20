#!/usr/bin/env node
/** Author-side type and minimum-SDK check. Never evaluates plugin code. */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const sdkRoot = path.dirname(fileURLToPath(import.meta.url));
function version(value) {
  const match = /^(\d+)\.(\d+)(?:\.(\d+))?(.*)$/.exec(value ?? "");
  if (!match) throw new Error("plugin.json must declare sdk.version");
  return [
    +match[1],
    +match[2],
    +(match[3] ?? 0),
    /^(?:[.-]?(?:a|b|rc|dev)|-(?!post))/.test(match[4]) ? -1 : 0,
  ];
}
function older(left, right) {
  const at = left.findIndex((part, i) => part !== right[i]);
  return at >= 0 && left[at] < right[at];
}

export function checkProject(manifestPath, projectPath) {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const minimum = version(manifest.sdk?.version);
  projectPath = path.resolve(projectPath);
  const ts = createRequire(projectPath)("typescript");
  const config = ts.readConfigFile(projectPath, ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(
    config.config ?? {},
    ts.sys,
    path.dirname(projectPath),
  );
  const program = ts.createProgram(parsed.fileNames, {
    ...parsed.options,
    strict: true,
    noEmit: true,
    allowJs: true,
    checkJs: true,
  });
  const checker = program.getTypeChecker();
  const findings = [],
    seen = new Set();
  function add(node, rule, message) {
    const source = node.getSourceFile();
    const position = source.getLineAndCharacterOfPosition(node.getStart());
    const row = {
      file: source.fileName,
      line: position.line + 1,
      column: position.character + 1,
      rule,
      message,
    };
    const key = JSON.stringify(row);
    if (!seen.has(key)) {
      seen.add(key);
      findings.push(row);
    }
  }
  // Symbols are resolved by TypeScript, not by matching names in source text.
  // Only annotations in this installed SDK's declarations are authoritative.
  function requireSymbol(symbol, node) {
    if (!symbol) return;
    if (symbol.flags & ts.SymbolFlags.Alias)
      symbol = checker.getAliasedSymbol(symbol);
    for (let declaration of symbol.declarations ?? []) {
      if (path.dirname(declaration.getSourceFile().fileName) !== sdkRoot)
        continue;
      while (declaration && !ts.isSourceFile(declaration)) {
        for (const tag of ts.getJSDocTags(declaration)) {
          if (tag.tagName.text !== "since" || typeof tag.comment !== "string")
            continue;
          const since = tag.comment.split(/\s/)[0];
          if (older(minimum, version(since)))
            add(
              node,
              "sdk-version",
              `${symbol.name} requires SDK >= ${since}; declared ${manifest.sdk.version}`,
            );
        }
        declaration = declaration.parent;
      }
    }
  }
  function checkFields(actual, expected, node, visited = new Map()) {
    expected = checker.getNonNullableType(expected);
    const targets = visited.get(actual) ?? new Set();
    if (targets.has(expected)) return;
    targets.add(expected);
    visited.set(actual, targets);
    for (const field of checker.getPropertiesOfType(actual)) {
      const target = checker.getPropertyOfType(expected, field.name);
      if (!target) continue;
      requireSymbol(target, node);
      // Recurse only through actual object shapes, not function/library types.
      const value = checker.getTypeOfSymbolAtLocation(field, node);
      const wanted = checker.getTypeOfSymbolAtLocation(target, node);
      if (
        value.flags & ts.TypeFlags.Object &&
        value.getCallSignatures().length === 0
      )
        checkFields(value, wanted, node, visited);
    }
  }
  function visit(node) {
    if (ts.isIdentifier(node) || ts.isStringLiteralLike(node))
      requireSymbol(checker.getSymbolAtLocation(node), node);
    if (ts.isCallExpression(node)) {
      const signature = checker.getResolvedSignature(node);
      if (signature)
        node.arguments.forEach((argument, i) => {
          const parameter = signature.parameters[i];
          if (parameter)
            checkFields(
              checker.getTypeAtLocation(argument),
              checker.getTypeOfSymbolAtLocation(parameter, node),
              argument,
            );
        });
    }
    if (
      ts.isPropertyAssignment(node) ||
      ts.isShorthandPropertyAssignment(node)
    ) {
      const expected = checker.getContextualType(node.parent);
      if (expected)
        requireSymbol(
          checker.getPropertyOfType(
            expected,
            node.name.getText().replace(/^["']|["']$/g, ""),
          ),
          node.name,
        );
    }
    ts.forEachChild(node, visit);
  }
  const sources = program
    .getSourceFiles()
    .filter(
      (source) =>
        !source.isDeclarationFile &&
        !program.isSourceFileFromExternalLibrary(source),
    );
  for (const source of sources) visit(source);
  for (const diagnostic of [
    config.error,
    ...parsed.errors,
    ...ts.getPreEmitDiagnostics(program),
  ].filter(Boolean)) {
    const pos =
      diagnostic.file && diagnostic.start !== undefined
        ? diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start)
        : null;
    findings.push({
      file: diagnostic.file?.fileName ?? projectPath,
      line: pos ? pos.line + 1 : 1,
      column: pos ? pos.character + 1 : 1,
      rule: `TS${diagnostic.code}`,
      message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
    });
  }
  if (!sources.length)
    findings.push({
      file: projectPath,
      line: 1,
      column: 1,
      rule: "input",
      message: "No author source files were checked",
    });
  return {
    ok: findings.length === 0,
    declared_sdk_version: manifest.sdk.version,
    files: sources.map((source) => source.fileName),
    findings,
    limitations: [
      "Checks this TypeScript project, not omitted sources or a deployed bundle; any, casts and suppression comments can hide usage. Run the Python SDK checker separately.",
    ],
  };
}

if (
  process.argv[1] &&
  fs.realpathSync(process.argv[1]) ===
    fs.realpathSync(fileURLToPath(import.meta.url))
) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 2)
      throw new Error(
        "Usage: qwenpaw-sdk-check path/to/plugin.json path/to/tsconfig.json (requires project-local typescript)",
      );
    const result = checkProject(...args);
    console.log(JSON.stringify(result, null, 2));
    process.exitCode = result.ok ? 0 : 1;
  } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}
