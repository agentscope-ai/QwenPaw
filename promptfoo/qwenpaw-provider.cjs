const DEFAULT_BASE_URL = 'http://127.0.0.1:8088';
const DEFAULT_TIMEOUT_MS = 180000;

class QwenPawProvider {
  constructor(options = {}) {
    this.config = options.config || {};
  }

  id() {
    return 'qwenpaw-local-console';
  }

  async callApi(prompt, context = {}) {
    const config = normalizeConfig(this.config);
    const promptText = normalizePrompt(prompt);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), config.timeoutMs);

    try {
      const response = await fetch(`${config.baseUrl}/api/console/chat`, {
        method: 'POST',
        headers: buildHeaders(config),
        body: JSON.stringify(buildRequestBody(promptText, context)),
        signal: controller.signal,
      });

      const raw = await response.text();

      if (!response.ok) {
        return {
          error: `QwenPaw returned HTTP ${response.status}: ${truncate(raw, 2000)}`,
        };
      }

      const output = extractOutput(raw);
      return {
        output: output || raw,
        metadata: {
          status: response.status,
          contentType: response.headers.get('content-type') || '',
        },
      };
    } catch (error) {
      return {
        error: error && error.name === 'AbortError'
          ? `QwenPaw request timed out after ${config.timeoutMs}ms`
          : `QwenPaw request failed: ${error && error.message ? error.message : String(error)}`,
      };
    } finally {
      clearTimeout(timeout);
    }
  }
}

function normalizeConfig(config) {
  return {
    baseUrl: cleanTemplateValue(config.baseUrl, process.env.QWENPAW_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ''),
    agentId: cleanTemplateValue(config.agentId, process.env.QWENPAW_AGENT_ID || ''),
    authToken: cleanTemplateValue(config.authToken, process.env.QWENPAW_AUTH_TOKEN || ''),
    timeoutMs: normalizeTimeout(config.timeoutMs),
  };
}

function normalizeTimeout(value) {
  const raw = cleanTemplateValue(value, process.env.QWENPAW_TIMEOUT_MS || String(DEFAULT_TIMEOUT_MS));
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

function cleanTemplateValue(value, fallback) {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (typeof value !== 'string') {
    return value;
  }
  const trimmed = value.trim();
  if (!trimmed || trimmed.startsWith('{{')) {
    return fallback;
  }
  return trimmed;
}

function normalizePrompt(prompt) {
  if (typeof prompt === 'string') {
    return prompt;
  }
  return JSON.stringify(prompt);
}

function buildHeaders(config) {
  const headers = {
    Accept: 'text/event-stream, application/json, text/plain',
    'Content-Type': 'application/json',
    'User-Agent': 'promptfoo-qwenpaw-redteam',
  };

  if (config.authToken) {
    headers.Authorization = `Bearer ${config.authToken}`;
  }
  if (config.agentId) {
    headers['X-Agent-Id'] = config.agentId;
  }

  return headers;
}

function buildRequestBody(promptText, context) {
  return {
    input: [
      {
        role: 'user',
        content: [
          {
            type: 'text',
            text: promptText,
          },
        ],
      },
    ],
    session_id: buildSessionId(context),
    user_id: 'promptfoo',
    channel: 'console',
    stream: true,
  };
}

function buildSessionId(context) {
  const vars = context.vars || {};
  if (vars.session_id) {
    return String(vars.session_id);
  }

  const metadata = context.test && context.test.metadata ? context.test.metadata : {};
  const plugin = sanitizeId(metadata.pluginId || vars.pluginId || 'smoke');
  const strategy = sanitizeId(metadata.strategyId || vars.strategyId || 'basic');
  const suffix = Math.random().toString(36).slice(2, 8);
  return `promptfoo-${plugin}-${strategy}-${Date.now()}-${suffix}`;
}

function sanitizeId(value) {
  return String(value).replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'case';
}

function extractOutput(raw) {
  const sseOutput = extractSseOutput(raw);
  if (sseOutput) {
    return sseOutput;
  }

  try {
    const json = JSON.parse(raw);
    return extractTextFromAny(json).join('\n').trim() || JSON.stringify(json);
  } catch {
    return raw.trim();
  }
}

function extractSseOutput(raw) {
  const finalTexts = [];
  const deltaTexts = [];

  for (const block of raw.split(/\r?\n\r?\n/)) {
    const dataLines = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());

    if (!dataLines.length) {
      continue;
    }

    const data = dataLines.join('\n');
    if (!data || data === '[DONE]') {
      continue;
    }

    try {
      const event = JSON.parse(data);
      const extracted = extractTextFromQwenPawEvent(event);
      finalTexts.push(...extracted.finalTexts);
      deltaTexts.push(...extracted.deltaTexts);
    } catch {
      deltaTexts.push(data);
    }
  }

  return uniqueJoin(finalTexts) || uniqueJoin(deltaTexts);
}

function extractTextFromQwenPawEvent(event) {
  const finalTexts = [];
  const deltaTexts = [];
  const isCompleted = event.status === 'completed' || event.object === 'response.completed';

  if (event.object === 'response' || event.type === 'response') {
    if (isCompleted || Array.isArray(event.output)) {
      collectOutputItems(event.output, finalTexts);
    }
    collectTextFields(event, deltaTexts);
  }

  if (event.object === 'message' || event.type === 'message') {
    if (isCompleted || event.role === 'assistant') {
      collectContent(event.content, finalTexts);
    }
    collectTextFields(event, deltaTexts);
  }

  collectDelta(event.delta, deltaTexts);
  collectDelta(event.choices, deltaTexts);

  return { finalTexts, deltaTexts };
}

function collectOutputItems(output, texts) {
  if (!Array.isArray(output)) {
    return;
  }

  for (const item of output) {
    collectContent(item && item.content, texts);
    collectTextFields(item, texts);
  }
}

function collectContent(content, texts) {
  if (typeof content === 'string') {
    texts.push(content);
    return;
  }

  if (!Array.isArray(content)) {
    return;
  }

  for (const part of content) {
    if (!part) {
      continue;
    }
    if (typeof part === 'string') {
      texts.push(part);
    } else {
      collectTextFields(part, texts);
    }
  }
}

function collectTextFields(value, texts) {
  if (!value || typeof value !== 'object') {
    return;
  }

  for (const key of ['output_text', 'text', 'refusal']) {
    if (typeof value[key] === 'string' && value[key].trim()) {
      texts.push(value[key]);
    }
  }

  if (value.message) {
    collectContent(value.message.content, texts);
    collectTextFields(value.message, texts);
  }
}

function collectDelta(value, texts) {
  if (!value) {
    return;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      collectDelta(item, texts);
    }
    return;
  }

  if (typeof value === 'string') {
    texts.push(value);
    return;
  }

  if (typeof value === 'object') {
    collectTextFields(value, texts);
    collectContent(value.content, texts);
    collectDelta(value.delta, texts);
  }
}

function extractTextFromAny(value) {
  const texts = [];
  collectDelta(value, texts);
  collectOutputItems(value && value.output, texts);
  return texts;
}

function uniqueJoin(texts) {
  const seen = new Set();
  const cleaned = [];

  for (const text of texts) {
    const normalized = String(text).trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    cleaned.push(normalized);
  }

  return cleaned.join('\n').trim();
}

function truncate(value, maxLength) {
  const text = String(value || '');
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

module.exports = QwenPawProvider;
