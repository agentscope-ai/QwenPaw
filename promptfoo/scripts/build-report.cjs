#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

const SUITE_NAME_ZH = {
  approval: '审批绕过测试',
  'auth-api': '认证接口边界',
  benign: '正常请求回归',
  'browser-desktop': '浏览器桌面隐私',
  connectivity: '连通性测试',
  credentials: '凭据泄露测试',
  curated: '人工必测用例',
  'file-secret': '敏感文件测试',
  mcp: 'MCP 边界测试',
  'multi-agent': '多 Agent 绕过',
  'plugin-skill': '插件技能供应链',
  'prompt-extraction': '系统提示泄露',
  shell: '系统命令测试',
  'workspace-injection': '工作区提示注入',
};

const CATEGORY_NAME_ZH = {
  approval: '审批绕过',
  'auth-api': '认证接口边界',
  benign: '正常请求',
  'browser-desktop': '浏览器桌面隐私',
  connectivity: '连通性',
  credential: '凭据泄露',
  credentials: '凭据泄露',
  'file-secret': '敏感文件',
  mcp: 'MCP 边界',
  'multi-agent': '多 Agent 绕过',
  'plugin-skill': '插件技能供应链',
  'prompt-extraction': '系统提示泄露',
  secret: '敏感文件',
  shell: '系统命令',
  'shell-injection': '系统命令注入',
  'workspace-injection': '工作区提示注入',
};

const TAG_ALIASES = {
  approval: ['excessive-agency', 'rbac', 'bfla'],
  'auth-api': ['rbac', 'bfla', 'bola'],
  'browser-desktop': ['harmful:privacy', 'pii:session', 'excessive-agency'],
  credential: ['pii:direct', 'pii:api-db', 'harmful:privacy'],
  credentials: ['pii:direct', 'pii:api-db', 'harmful:privacy'],
  'file-secret': ['pii:direct', 'pii:api-db', 'harmful:privacy'],
  mcp: ['mcp', 'tool-discovery', 'excessive-agency'],
  'multi-agent': ['hijacking', 'imitation', 'indirect-prompt-injection'],
  'plugin-skill': ['indirect-prompt-injection', 'mcp'],
  'prompt-extraction': ['prompt-extraction', 'system-prompt-override'],
  secret: ['pii:direct', 'pii:api-db', 'harmful:privacy'],
  shell: ['shell-injection'],
  'shell-injection': ['shell'],
  'workspace-injection': ['indirect-prompt-injection', 'system-prompt-override'],
};

const FRAMEWORK_DEFINITIONS = [
  {
    id: 'owasp-llm',
    title: 'OWASP LLM Top 10',
    description: 'Promptfoo 官方 OWASP LLM Top 10 风险域映射视图。',
    items: [
      { id: 'owasp:llm:01', name: '01. Prompt Injection', plugins: ['ascii-smuggling', 'indirect-prompt-injection', 'prompt-extraction', 'harmful'] },
      { id: 'owasp:llm:02', name: '02. Sensitive Information Disclosure', plugins: ['pii:api-db', 'pii:direct', 'pii:session', 'pii:social', 'harmful:privacy', 'cross-session-leak', 'prompt-extraction'] },
      { id: 'owasp:llm:03', name: '03. Supply Chain', plugins: ['plugin-skill', 'mcp'] },
      { id: 'owasp:llm:04', name: '04. Data and Model Poisoning', plugins: ['harmful:misinformation-disinformation', 'harmful:hate', 'bias:age', 'bias:disability', 'bias:gender', 'bias:race'] },
      { id: 'owasp:llm:05', name: '05. Improper Output Handling', plugins: ['shell-injection', 'sql-injection', 'ssrf', 'debug-access'] },
      { id: 'owasp:llm:06', name: '06. Excessive Agency', plugins: ['excessive-agency', 'rbac', 'bfla', 'bola', 'shell-injection', 'sql-injection', 'ssrf'] },
      { id: 'owasp:llm:07', name: '07. System Prompt Leakage', plugins: ['prompt-extraction', 'rbac', 'harmful:privacy', 'pii:api-db', 'pii:direct', 'pii:session'] },
      { id: 'owasp:llm:08', name: '08. Vector and Embedding Weaknesses', plugins: ['cross-session-leak', 'harmful:privacy', 'pii:api-db', 'pii:direct', 'pii:session'] },
      { id: 'owasp:llm:09', name: '09. Misinformation', plugins: ['hallucination', 'overreliance', 'harmful:misinformation-disinformation'] },
      { id: 'owasp:llm:10', name: '10. Unbounded Consumption', plugins: ['divergent-repetition', 'reasoning-dos'] },
    ],
  },
  {
    id: 'owasp-agentic',
    title: 'OWASP Top 10 for Agentic Applications',
    description: '面向 Agent 工具调用、身份权限、上下文污染和多 Agent 风险的覆盖视图。',
    items: [
      { id: 'owasp:agentic:asi01', name: 'ASI01. Agent Goal Hijack', plugins: ['hijacking', 'system-prompt-override', 'indirect-prompt-injection', 'intent'] },
      { id: 'owasp:agentic:asi02', name: 'ASI02. Tool Misuse and Exploitation', plugins: ['excessive-agency', 'mcp', 'tool-discovery'] },
      { id: 'owasp:agentic:asi03', name: 'ASI03. Identity and Privilege Abuse', plugins: ['rbac', 'bfla', 'bola', 'imitation'] },
      { id: 'owasp:agentic:asi04', name: 'ASI04. Agentic Supply Chain Vulnerabilities', plugins: ['indirect-prompt-injection', 'mcp', 'plugin-skill'] },
      { id: 'owasp:agentic:asi05', name: 'ASI05. Unexpected Code Execution', plugins: ['shell-injection', 'sql-injection', 'harmful:cybercrime:malicious-code', 'ssrf'] },
      { id: 'owasp:agentic:asi06', name: 'ASI06. Memory and Context Poisoning', plugins: ['agentic:memory-poisoning', 'cross-session-leak', 'indirect-prompt-injection'] },
      { id: 'owasp:agentic:asi07', name: 'ASI07. Insecure Inter-Agent Communication', plugins: ['indirect-prompt-injection', 'hijacking', 'imitation'] },
      { id: 'owasp:agentic:asi08', name: 'ASI08. Cascading Failures', plugins: ['hallucination', 'harmful:misinformation-disinformation', 'divergent-repetition'] },
      { id: 'owasp:agentic:asi09', name: 'ASI09. Human Agent Trust Exploitation', plugins: ['overreliance', 'imitation', 'harmful:misinformation-disinformation'] },
      { id: 'owasp:agentic:asi10', name: 'ASI10. Rogue Agents', plugins: ['excessive-agency', 'hijacking', 'rbac', 'goal-misalignment'] },
    ],
  },
  {
    id: 'eu-ai-act',
    title: 'EU AI Act',
    description: '禁止性实践与高风险场景的测试覆盖视图。',
    items: [
      { id: 'eu:ai-act:art5:subliminal-manipulation', name: 'Art. 5 Subliminal Manipulation', plugins: ['hijacking', 'intent', 'excessive-agency', 'harmful:misinformation-disinformation'] },
      { id: 'eu:ai-act:art5:exploitation-of-vulnerabilities', name: 'Art. 5 Exploitation of Vulnerabilities', plugins: ['hijacking', 'imitation', 'bias:age', 'bias:disability'] },
      { id: 'eu:ai-act:art5:social-scoring', name: 'Art. 5 Social Scoring', plugins: ['overreliance', 'bias:age', 'bias:gender', 'bias:race', 'bias:disability'] },
      { id: 'eu:ai-act:art5:biometric-categorisation', name: 'Art. 5 Biometric Categorisation', plugins: ['pii:direct', 'pii:session', 'harmful:privacy'] },
      { id: 'eu:ai-act:annex3:critical-infrastructure', name: 'Annex III Critical Infrastructure', plugins: ['shell-injection', 'sql-injection', 'ssrf', 'excessive-agency'] },
      { id: 'eu:ai-act:annex3:employment', name: 'Annex III Employment', plugins: ['imitation', 'pii:direct', 'overreliance', 'bias:gender', 'bias:race'] },
      { id: 'eu:ai-act:annex3:essential-services', name: 'Annex III Essential Services', plugins: ['pii:direct', 'pii:session', 'excessive-agency', 'bias:race', 'bias:gender'] },
      { id: 'eu:ai-act:annex3:law-enforcement', name: 'Annex III Law Enforcement', plugins: ['pii:direct', 'pii:api-db', 'harmful:privacy', 'bias:race'] },
      { id: 'eu:ai-act:annex3:justice-democracy', name: 'Annex III Justice and Democracy', plugins: ['hallucination', 'harmful:misinformation-disinformation', 'pii:direct', 'bias:race', 'bias:gender'] },
    ],
  },
];

function parseArgs(argv) {
  const options = {
    resultsDir: path.join(ROOT, 'results'),
    templatesDir: path.join(ROOT, 'report-templates'),
    outDir: path.join(ROOT, 'reports'),
  };

  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === '--results' && next) {
      options.resultsDir = path.resolve(ROOT, next);
      i += 1;
    } else if (arg === '--templates' && next) {
      options.templatesDir = path.resolve(ROOT, next);
      i += 1;
    } else if (arg === '--out' && next) {
      options.outDir = path.resolve(ROOT, next);
      i += 1;
    } else if (arg === '--help' || arg === '-h') {
      console.log('Usage: node scripts/build-report.cjs [--results results] [--templates report-templates] [--out reports]');
      process.exit(0);
    }
  }

  return options;
}

function toText(value) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function redact(value) {
  return toText(value)
    .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '***REDACTED_PRIVATE_KEY***')
    .replace(/\bsk-[A-Za-z0-9_-]{10,}\b/g, '***REDACTED_OPENAI_STYLE_KEY***')
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b/gi, 'Bearer ***REDACTED***')
    .replace(/\bghp_[A-Za-z0-9_]{16,}\b/g, '***REDACTED_GITHUB_TOKEN***')
    .replace(/\bgithub_pat_[A-Za-z0-9_]{20,}\b/g, '***REDACTED_GITHUB_TOKEN***')
    .replace(/\bAIza[0-9A-Za-z_-]{20,}\b/g, '***REDACTED_GOOGLE_KEY***')
    .replace(/\b(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|DEEPSEEK_API_KEY|OPENAI_API_KEY|PROMPTFOO_OPENAI_API_KEY|QWENPAW_AUTH_TOKEN)\s*[:=]\s*["']?[^"'\s,;]+/gi, '$1=***REDACTED***')
    .replace(/\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION)[A-Z0-9_]*)\s*[:=]\s*["']?[^"'\s,;]{8,}/gi, '$1=***REDACTED***')
    .replace(/(Authorization\s*:\s*)[^\r\n]+/gi, '$1***REDACTED***');
}

function pct(part, total) {
  return total > 0 ? (part / total) * 100 : 0;
}

function classify(row) {
  if (row && row.success === true) return 'PASS';

  const reason = [
    row?.failureReason,
    row?.gradingResult?.reason,
    row?.response?.error,
    row?.error,
  ].map(toText).join('\n');

  if (/Provider call failed|Custom function threw|API key is not set|ECONN|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|timeout|Cannot find module|ENOENT|empty response|QwenPaw returned an empty response/i.test(reason)) {
    return 'ERROR';
  }

  return 'FAIL';
}

function getPrompt(row) {
  return row?.vars?.prompt
    ?? row?.testCase?.vars?.prompt
    ?? row?.prompt?.raw
    ?? row?.prompt
    ?? '';
}

function getOutput(row) {
  const response = row?.response;
  if (response && typeof response === 'object') {
    return response.output ?? response.text ?? response.content ?? response.error ?? response;
  }
  return response ?? row?.output ?? '';
}

function getReason(row) {
  return row?.gradingResult?.reason
    ?? row?.gradingResult?.componentResults?.find?.((item) => item?.reason)?.reason
    ?? (typeof row?.failureReason === 'string' ? row.failureReason : '')
    ?? row?.response?.error
    ?? row?.error
    ?? '';
}

function getPlugin(row) {
  return row?.metadata?.pluginId
    ?? row?.testCase?.metadata?.pluginId
    ?? row?.vars?.pluginId
    ?? '';
}

function getStrategy(row) {
  return row?.metadata?.strategyId
    ?? row?.testCase?.metadata?.strategyId
    ?? '';
}

function getCategory(row, suite) {
  return row?.vars?.category
    ?? row?.testCase?.vars?.category
    ?? getPlugin(row)
    ?? suite
    ?? 'uncategorized';
}

function addCount(map, key, status, latencyMs) {
  if (!map.has(key)) {
    map.set(key, { key, total: 0, passed: 0, failed: 0, errors: 0, latencyTotal: 0, latencyCount: 0 });
  }
  const item = map.get(key);
  item.total += 1;
  if (status === 'PASS') item.passed += 1;
  if (status === 'FAIL') item.failed += 1;
  if (status === 'ERROR') item.errors += 1;
  if (typeof latencyMs === 'number' && Number.isFinite(latencyMs)) {
    item.latencyTotal += latencyMs;
    item.latencyCount += 1;
  }
}

function getSuiteNameZh(suite) {
  return SUITE_NAME_ZH[suite] || suite;
}

function getCategoryNameZh(category) {
  return CATEGORY_NAME_ZH[category] || SUITE_NAME_ZH[category] || category;
}

function normalizeSummary(item, labelName, getNameZh) {
  return {
    [labelName]: item.key,
    nameZh: getNameZh(item.key),
    total: item.total,
    passed: item.passed,
    failed: item.failed,
    errors: item.errors,
    passRate: pct(item.passed, item.total),
    avgLatencyMs: item.latencyCount > 0 ? item.latencyTotal / item.latencyCount : 0,
  };
}

function normalizeTag(value) {
  return toText(value).trim().toLowerCase();
}

function expandTag(tag, tags) {
  const normalized = normalizeTag(tag);
  if (!normalized || tags.has(normalized)) return;
  tags.add(normalized);
  (TAG_ALIASES[normalized] || []).forEach((alias) => expandTag(alias, tags));
}

function tagsForCase(item) {
  const tags = new Set();
  [item.suite, item.category, item.plugin, item.strategy].forEach((value) => expandTag(value, tags));
  return tags;
}

function summarizeFrameworkItem(definition, taggedCases) {
  const pluginTags = definition.plugins.map(normalizeTag).filter(Boolean);
  const matchingCases = taggedCases
    .filter((item) => pluginTags.some((tag) => item.tags.has(tag)))
    .map((item) => item.caseItem);

  const total = matchingCases.length;
  const passed = matchingCases.filter((item) => item.status === 'PASS').length;
  const failed = matchingCases.filter((item) => item.status === 'FAIL').length;
  const errors = matchingCases.filter((item) => item.status === 'ERROR').length;
  const status = total === 0 ? 'NOT_TESTED' : (failed > 0 || errors > 0 ? 'FAIL' : 'PASS');

  return {
    id: definition.id,
    name: definition.name,
    plugins: definition.plugins,
    status,
    total,
    passed,
    failed,
    errors,
    passRate: pct(passed, total),
  };
}

function buildFrameworkCoverage(cases) {
  const taggedCases = cases.map((caseItem) => ({
    caseItem,
    tags: tagsForCase(caseItem),
  }));

  return FRAMEWORK_DEFINITIONS.map((framework) => {
    const items = framework.items.map((item) => summarizeFrameworkItem(item, taggedCases));
    const tested = items.filter((item) => item.status !== 'NOT_TESTED').length;
    const failed = items.filter((item) => item.status === 'FAIL').length;
    const passed = items.filter((item) => item.status === 'PASS').length;
    const notTested = items.length - tested;

    return {
      id: framework.id,
      title: framework.title,
      description: framework.description,
      total: items.length,
      tested,
      passed,
      failed,
      notTested,
      passRate: pct(passed, tested),
      items,
    };
  });
}

function loadResults(resultsDir) {
  if (!fs.existsSync(resultsDir)) {
    throw new Error(`Results directory not found: ${resultsDir}`);
  }

  const files = fs.readdirSync(resultsDir)
    .filter((file) => file.endsWith('.results.json'))
    .sort();

  if (files.length === 0) {
    throw new Error(`No *.results.json files found in ${resultsDir}`);
  }

  const suiteMap = new Map();
  const categoryMap = new Map();
  const cases = [];

  for (const file of files) {
    const suite = file.replace(/\.results\.json$/, '');
    const fullPath = path.join(resultsDir, file);
    const payload = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
    const rows = payload?.results?.results;
    if (!Array.isArray(rows)) {
      continue;
    }

    rows.forEach((row, index) => {
      const status = classify(row);
      const category = toText(getCategory(row, suite)) || suite;
      const latencyMs = typeof row?.latencyMs === 'number' ? row.latencyMs : null;

      addCount(suiteMap, suite, status, latencyMs);
      addCount(categoryMap, category, status, latencyMs);

      cases.push({
        id: row?.id ?? `${suite}-${index}`,
        suite,
        suiteNameZh: getSuiteNameZh(suite),
        sourceFile: file,
        status,
        category,
        categoryNameZh: getCategoryNameZh(category),
        description: redact(row?.testCase?.description ?? row?.description ?? ''),
        plugin: redact(getPlugin(row)),
        strategy: redact(getStrategy(row)),
        prompt: redact(getPrompt(row)),
        output: redact(getOutput(row)),
        reason: redact(getReason(row)),
        score: row?.score ?? row?.gradingResult?.score ?? null,
        latencyMs,
        tokenUsage: row?.tokenUsage ?? row?.response?.tokenUsage ?? null,
      });
    });
  }

  const overall = cases.reduce((acc, item) => {
    acc.total += 1;
    if (item.status === 'PASS') acc.passed += 1;
    if (item.status === 'FAIL') acc.failed += 1;
    if (item.status === 'ERROR') acc.errors += 1;
    return acc;
  }, { total: 0, passed: 0, failed: 0, errors: 0 });
  overall.passRate = pct(overall.passed, overall.total);
  const sortedCases = cases.sort((a, b) => {
    const order = { ERROR: 0, FAIL: 1, PASS: 2 };
    return (order[a.status] - order[b.status]) || a.suite.localeCompare(b.suite) || a.category.localeCompare(b.category);
  });

  return {
    generatedAt: new Date().toISOString(),
    sourceFiles: files,
    overall,
    suites: [...suiteMap.values()].map((item) => normalizeSummary(item, 'suite', getSuiteNameZh)).sort((a, b) => a.suite.localeCompare(b.suite)),
    categories: [...categoryMap.values()].map((item) => normalizeSummary(item, 'category', getCategoryNameZh)).sort((a, b) => a.category.localeCompare(b.category)),
    frameworks: buildFrameworkCoverage(sortedCases),
    cases: sortedCases,
  };
}

function mdTable(headers, rows) {
  const header = `| ${headers.join(' | ')} |`;
  const sep = `| ${headers.map(() => '---').join(' | ')} |`;
  const body = rows.map((row) => `| ${row.map((cell) => toText(cell).replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>')).join(' | ')} |`);
  return [header, sep, ...body].join('\n');
}

function formatRate(value) {
  return `${value.toFixed(1)}%`;
}

function truncate(value, max = 220) {
  const valueText = toText(value).replace(/\s+/g, ' ').trim();
  return valueText.length > max ? `${valueText.slice(0, max - 1)}…` : valueText;
}

function buildSummaryMarkdown(data, template) {
  const suiteTable = mdTable(
    ['测试套件', '中文名称', '总数', '通过', '失败', '异常', '通过率'],
    data.suites.map((s) => [s.suite, s.nameZh, s.total, s.passed, s.failed, s.errors, formatRate(s.passRate)]),
  );

  const categoryTable = mdTable(
    ['分类', '中文名称', '总数', '通过', '失败', '异常', '通过率'],
    data.categories.map((c) => [c.category, c.nameZh, c.total, c.passed, c.failed, c.errors, formatRate(c.passRate)]),
  );

  const frameworkTable = mdTable(
    ['框架', '覆盖项', '已测试', '通过项', '失败项', '未测试', '已测通过率'],
    data.frameworks.map((f) => [
      f.title,
      f.total,
      f.tested,
      f.passed,
      f.failed,
      f.notTested,
      f.tested > 0 ? formatRate(f.passRate) : 'N/A',
    ]),
  );

  const failures = data.cases.filter((item) => item.status === 'FAIL');
  const errors = data.cases.filter((item) => item.status === 'ERROR');

  const failureList = failures.length === 0
    ? '无失败用例。'
    : mdTable(
      ['测试套件', '分类', '描述', '测试输入', '判定原因'],
      failures.map((item) => [item.suite, item.category, item.description, truncate(item.prompt), truncate(item.reason)]),
    );

  const errorList = errors.length === 0
    ? '无异常用例。'
    : mdTable(
      ['测试套件', '分类', '描述', '测试输入', '判定原因'],
      errors.map((item) => [item.suite, item.category, item.description, truncate(item.prompt), truncate(item.reason)]),
    );

  const replacements = {
    generatedAt: data.generatedAt,
    resultFileCount: data.sourceFiles.length,
    overallTotal: data.overall.total,
    overallPassed: data.overall.passed,
    overallFailed: data.overall.failed,
    overallErrors: data.overall.errors,
    overallPassRate: formatRate(data.overall.passRate),
    suiteTable,
    categoryTable,
    frameworkTable,
    failureList,
    errorList,
    sourceFiles: data.sourceFiles.map((file) => `- \`${file}\``).join('\n'),
  };

  return template.replace(/\{\{(\w+)\}\}/g, (_, key) => {
    return Object.prototype.hasOwnProperty.call(replacements, key) ? toText(replacements[key]) : '';
  });
}

function safeInlineJson(value) {
  return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, (char) => {
    switch (char) {
      case '<':
        return '\\u003c';
      case '>':
        return '\\u003e';
      case '&':
        return '\\u0026';
      case '\u2028':
        return '\\u2028';
      case '\u2029':
        return '\\u2029';
      default:
        return char;
    }
  });
}

function copyDirectory(sourceDir, targetDir) {
  fs.mkdirSync(targetDir, { recursive: true });

  for (const entry of fs.readdirSync(sourceDir, { withFileTypes: true })) {
    const sourcePath = path.join(sourceDir, entry.name);
    const targetPath = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      copyDirectory(sourcePath, targetPath);
    } else if (entry.isFile()) {
      fs.copyFileSync(sourcePath, targetPath);
    }
  }
}

function copyTemplateAssets(templatesDir, outDir) {
  const sourceDir = path.join(templatesDir, 'assets');
  if (!fs.existsSync(sourceDir)) {
    return;
  }

  const targetDir = path.join(outDir, 'assets');
  copyDirectory(sourceDir, targetDir);
}

function copySourceFiles(sourceFiles, resultsDir, outDir) {
  const targetDir = path.join(outDir, 'source-files');
  fs.rmSync(targetDir, { recursive: true, force: true });
  fs.mkdirSync(targetDir, { recursive: true });

  for (const file of sourceFiles) {
    const sourcePath = path.join(resultsDir, file);
    const targetPath = path.join(targetDir, file);
    if (fs.existsSync(sourcePath) && fs.statSync(sourcePath).isFile()) {
      fs.copyFileSync(sourcePath, targetPath);
    }
  }
}

function buildSourceFileDownloads(sourceFiles, resultsDir) {
  const downloads = {};
  for (const file of sourceFiles) {
    const sourcePath = path.join(resultsDir, file);
    if (fs.existsSync(sourcePath) && fs.statSync(sourcePath).isFile()) {
      downloads[file] = {
        mimeType: 'application/json',
        base64: fs.readFileSync(sourcePath).toString('base64'),
      };
    }
  }
  return downloads;
}

function main() {
  const options = parseArgs(process.argv);
  const data = loadResults(options.resultsDir);

  fs.mkdirSync(options.outDir, { recursive: true });
  copyTemplateAssets(options.templatesDir, options.outDir);
  copySourceFiles(data.sourceFiles, options.resultsDir, options.outDir);

  const htmlTemplatePath = path.join(options.templatesDir, 'report.html');
  const mdTemplatePath = path.join(options.templatesDir, 'summary.md');
  const htmlTemplate = fs.readFileSync(htmlTemplatePath, 'utf8');
  const mdTemplate = fs.readFileSync(mdTemplatePath, 'utf8');

  const sourceFileDownloads = buildSourceFileDownloads(data.sourceFiles, options.resultsDir);
  const html = htmlTemplate
    .replace('__REPORT_DATA_JSON__', safeInlineJson(data))
    .replace('__SOURCE_FILE_DOWNLOADS_JSON__', safeInlineJson(sourceFileDownloads));
  const summary = buildSummaryMarkdown(data, mdTemplate);

  fs.writeFileSync(path.join(options.outDir, 'index.html'), html, 'utf8');
  fs.writeFileSync(path.join(options.outDir, 'summary.md'), summary, 'utf8');
  fs.writeFileSync(path.join(options.outDir, 'summary.json'), JSON.stringify(data, null, 2), 'utf8');

  console.log(`Report written to ${path.relative(ROOT, path.join(options.outDir, 'index.html'))}`);
  console.log(`Summary written to ${path.relative(ROOT, path.join(options.outDir, 'summary.md'))}`);
  console.log(`Machine summary written to ${path.relative(ROOT, path.join(options.outDir, 'summary.json'))}`);
}

try {
  main();
} catch (err) {
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
}
