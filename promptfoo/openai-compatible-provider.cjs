const DEFAULT_BASE_URL = 'https://api.deepseek.com/v1';
const DEFAULT_MODEL = 'deepseek-chat';
const DEFAULT_TIMEOUT_MS = 180000;
const DEFAULT_MAX_TOKENS = 12000;
const DEFAULT_TEMPERATURE = 0.3;

class OpenAiCompatibleProvider {
  constructor(options = {}) {
    this.config = options.config || {};
  }

  id() {
    const config = normalizeConfig(this.config);
    return `openai-compatible:${config.model}`;
  }

  async callApi(prompt) {
    const config = normalizeConfig(this.config);
    if (!config.apiKey) {
      return {
        error:
          'OpenAI-compatible API key is not set. Set PROMPTFOO_OPENAI_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY.',
      };
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), config.timeoutMs);

    try {
      const response = await fetch(buildChatCompletionsUrl(config.baseUrl), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${config.apiKey}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          model: config.model,
          messages: [{ role: 'user', content: normalizePrompt(prompt) }],
          temperature: config.temperature,
          max_tokens: config.maxTokens,
        }),
        signal: controller.signal,
      });

      const raw = await response.text();
      if (!response.ok) {
        return {
          error: `OpenAI-compatible provider returned HTTP ${response.status}: ${truncate(raw, 2000)}`,
        };
      }

      let data;
      try {
        data = JSON.parse(raw);
      } catch {
        return { output: raw.trim() };
      }

      const output = extractOutput(data);
      if (!output) {
        return {
          error: `OpenAI-compatible provider returned no final message content${formatFinishReason(
            data,
          )}. Increase PROMPTFOO_OPENAI_MAX_TOKENS or use a non-reasoning chat model. Raw response starts with: ${truncate(
            raw,
            1000,
          )}`,
          tokenUsage: normalizeUsage(data.usage),
        };
      }

      return {
        output,
        tokenUsage: normalizeUsage(data.usage),
        metadata: {
          model: config.model,
          baseUrl: config.baseUrl,
        },
      };
    } catch (error) {
      return {
        error:
          error && error.name === 'AbortError'
            ? `OpenAI-compatible provider timed out after ${config.timeoutMs}ms`
            : `OpenAI-compatible provider failed: ${error && error.message ? error.message : String(error)}`,
      };
    } finally {
      clearTimeout(timeout);
    }
  }
}

function normalizeConfig(config) {
  return {
    baseUrl: cleanTemplateValue(
      config.apiBaseUrl || config.baseUrl,
      process.env.PROMPTFOO_OPENAI_BASE_URL ||
        process.env.OPENAI_API_BASE_URL ||
        process.env.OPENAI_BASE_URL ||
        DEFAULT_BASE_URL,
    ).replace(/\/+$/, ''),
    apiKey: cleanTemplateValue(
      config.apiKey,
      process.env.PROMPTFOO_OPENAI_API_KEY ||
        process.env.OPENAI_API_KEY ||
        process.env.DEEPSEEK_API_KEY ||
        '',
    ),
    model: cleanTemplateValue(
      config.model,
      process.env.PROMPTFOO_OPENAI_MODEL || process.env.OPENAI_MODEL || DEFAULT_MODEL,
    ),
    timeoutMs: normalizeNumber(
      config.timeoutMs,
      process.env.PROMPTFOO_OPENAI_TIMEOUT_MS,
      DEFAULT_TIMEOUT_MS,
    ),
    maxTokens: normalizeNumber(
      config.max_tokens || config.maxTokens,
      process.env.PROMPTFOO_OPENAI_MAX_TOKENS,
      DEFAULT_MAX_TOKENS,
    ),
    temperature: normalizeNumber(
      config.temperature,
      process.env.PROMPTFOO_OPENAI_TEMPERATURE,
      DEFAULT_TEMPERATURE,
    ),
  };
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

function normalizeNumber(value, fallback, defaultValue) {
  const raw = cleanTemplateValue(value, fallback || String(defaultValue));
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue;
}

function normalizePrompt(prompt) {
  if (typeof prompt === 'string') {
    return prompt;
  }
  return JSON.stringify(prompt);
}

function buildChatCompletionsUrl(baseUrl) {
  if (/\/chat\/completions$/i.test(baseUrl)) {
    return baseUrl;
  }
  return `${baseUrl}/chat/completions`;
}

function extractOutput(data) {
  const topLevelOutput = firstNonEmpty([
    typeof data.output_text === 'string' ? data.output_text : '',
    contentToText(data.output),
    contentToText(data.content),
  ]);
  if (topLevelOutput) {
    return topLevelOutput;
  }

  const choice = Array.isArray(data.choices) ? data.choices[0] : undefined;
  const message = choice && choice.message;
  return firstNonEmpty([
    message ? contentToText(message.content) : '',
    choice && typeof choice.text === 'string' ? choice.text : '',
  ]);
}

function contentToText(content) {
  if (typeof content === 'string') {
    return content.trim();
  }
  if (!Array.isArray(content)) {
    return '';
  }
  return firstNonEmpty([
    content
      .map((part) => {
        if (typeof part === 'string') {
          return part;
        }
        if (!part || typeof part !== 'object') {
          return '';
        }
        if (typeof part.text === 'string') {
          return part.text;
        }
        if (typeof part.content === 'string') {
          return part.content;
        }
        if (Array.isArray(part.content)) {
          return contentToText(part.content);
        }
        return '';
      })
      .filter(Boolean)
      .join('\n'),
  ]);
}

function firstNonEmpty(values) {
  for (const value of values) {
    const text = String(value || '').trim();
    if (text) {
      return text;
    }
  }
  return '';
}

function formatFinishReason(data) {
  const choice = Array.isArray(data.choices) ? data.choices[0] : undefined;
  const reason = choice && (choice.finish_reason || choice.stop_reason);
  return reason ? ` (finish_reason: ${reason})` : '';
}

function normalizeUsage(usage) {
  if (!usage || typeof usage !== 'object') {
    return undefined;
  }
  return {
    total: usage.total_tokens,
    prompt: usage.prompt_tokens,
    completion: usage.completion_tokens,
  };
}

function truncate(value, maxLength) {
  const text = String(value || '');
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

module.exports = OpenAiCompatibleProvider;
