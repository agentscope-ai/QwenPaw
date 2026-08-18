# Embedding Models

Suppose you told QwenPaw a month ago, “We will keep the current database for this release and reassess migration afterward.” Today you ask, “Why did we stay with the old data setup?”

The two sentences mean nearly the same thing but share few keywords. A keyword-only search may miss the memory. Embeddings help QwenPaw recognize content whose meaning is similar even when the wording is different.

An embedding is not another memory system, and it does not generate an answer. It simply adds semantic retrieval to the memories you already have.

## How Embeddings Help Long-Term Memory

QwenPaw still stores memories as Markdown files in the workspace. When Embedding is enabled, ReMeLight generates vectors for text under `memory/` and `digest/`, then searches through two complementary paths:

- **BM25 keyword search** works well for exact terms such as function names, error codes, product names, and quoted wording.
- **Embedding semantic search** works well for synonyms, paraphrases, and topically related content.
- **RRF fusion** combines the rankings from both paths and puts more relevant memories first.

For example, the query “How does the user usually travel to work?” may not keyword-match “My preferred commute is a lightweight bicycle,” but semantic search can connect them. For `HTTP 409` or a specific function name, keyword search is usually more dependable.

Embeddings are optional. Without a configured model, BM25 and Wikilink expansion continue to work. A small knowledge base, or one searched mainly by exact terms, may not need vector retrieval at all.

## Think of a Vector as a Semantic Coordinate

An embedding model turns a piece of text into a fixed-length list of numbers: a vector. Texts with similar meanings are placed near one another, so they can be found by distance even when their words differ.

Documents and queries must be placed in the same compatible coordinate system. This leads to two important rules:

1. `dimensions` must match the model's actual output size; it is not an arbitrary target.
2. After changing the backend, endpoint, model, dimensions, or dimension-control behavior, rebuild the memory index.

Even if two models both return 1,024 numbers, they do not necessarily share a coordinate system. Document vectors created by the old model cannot safely be compared with query vectors from the new one.

Memory files remain the source of truth. Vectors and indexes are derived data that QwenPaw can recreate. Rebuilding the index does not rewrite your Markdown memories.

## Current Scope and Boundaries

QwenPaw connects to `openai`, `dashscope`, `dashscope_multimodal`, `gemini`, and `ollama` backends through AgentScope 2.x. ReMeLight is currently the only direct consumer of this configuration.

Keep these boundaries in mind:

- QwenPaw currently sends only **text** produced by ReMeLight. Selecting a multimodal type or model does not make QwenPaw parse images, audio, video, or PDFs.
- Embeddings do not capture or organize memories and do not provide a standalone agent tool. They only add a semantic signal to `memory_search` and digest similarity queries.
- Other memory backends, such as ADBPG, manage their own vector behavior and do not read this ReMeLight configuration.
- Identical inputs can use a local cache to reduce repeated computation and API calls.

## Configure in the Console

Open **Agent Config → Running Config → Long-term Memory → Embedding Model Config**:

1. Select the SDK type that matches the service interface.
2. Enter the model name, API key, and endpoint.
3. Enter the model's actual output dimensions.
4. Select **Test Embedding Service**.
5. Save after the test succeeds. If the Console reports a vector-space change, select **Rebuild Memory Index**.

![Embedding model configuration in the long-term memory settings](https://img.alicdn.com/imgextra/i2/O1CN01Er7z0tejkhL6wWB4_!!6000000004853-0-tps-3420-1314.jpg)

The setup moves through several distinct stages:

- **Enabled** means the current form contains the fields required to enable the backend. It does not prove that the service is reachable.
- **Verified** means the current form completed one real request and the returned dimensions matched the configuration.
- **Saved** means the settings were written to the running configuration and applied through a hot update or agent reload.
- **Rebuild required** means the semantic coordinate system changed and existing vectors must be regenerated.

![Verified Embedding service with its returned dimensions and latency](https://img.alicdn.com/imgextra/i1/O1CN01LQlWGm6qD4I1gTsS_!!6000000003153-0-tps-830-134.jpg)

The test sends one real text request. The result must arrive within 15 seconds, contain a non-empty vector of finite numbers, and match `dimensions`. This proves only that one call works with the current settings. Initial indexing or a rebuild still has to process existing memories and can encounter quotas, rate limits, or oversized inputs.

## Verify Semantic Retrieval

Use two sentences with similar meanings but little keyword overlap:

1. Save the memory: “My preferred commute is a lightweight bicycle.”
2. Search for: “How does the user usually travel to work?”
3. Check that the memory is recalled and that the raw result contains a numeric `vector=...` value.

```text
Call memory_search for "How does the user usually travel to work?" Return the raw tool result,
including the score, vector, and keyword fields, without summarizing or rewriting it.
```

- A numeric `vector` means the vector branch found the result; `-` means it did not.
- A numeric `keyword` means the BM25 branch found the result; `-` means it did not.
- `score` is normally the RRF-fused score. When only one path runs, it may be that branch's original score.

## Common Problems

### Dimension Mismatch

`dimensions` is used for strict validation. Unless both the model and API explicitly support variable dimensions, enter the model's native output size. If the configuration expects 256 dimensions but the service returns 1,024, the test fails:

<img class="embedding-dialog" src="https://img.alicdn.com/imgextra/i4/O1CN01ZFtJXcpF1MH1GnlE_!!6000000004901-0-tps-626-242.jpg" alt="Embedding test failing because the expected and returned dimensions differ" />

`use_dimensions` only controls whether the `openai` backend sends a dimension parameter. It does not disable response validation. Some OpenAI-compatible services reject this parameter; turn it off and set `dimensions` to the size the service actually returns.

### Search Behaves Strangely After a Model Change

After saving a new backend, endpoint, model, dimensions, or `use_dimensions` value, follow the Console prompt and rebuild the index. Changing only the API key does not change the vector space and does not require a rebuild.

<img class="embedding-dialog" src="https://img.alicdn.com/imgextra/i3/O1CN01BCTjXC0jfMG1GYA0_!!6000000005728-0-tps-624-276.jpg" alt="Confirmation shown before rebuilding the memory index" />

### The Service Endpoint Is Unreachable

- For an OpenAI-compatible service, select `openai`; `base_url` is used as the API endpoint.
- DashScope currently uses the official SDK destination, so a custom `base_url` does not redirect its requests.
- Gemini currently does not use `base_url`.
- Ollama treats `base_url` as its `host`. When QwenPaw runs in a container, `localhost` refers to the container itself; use an address reachable from the QwenPaw process.

### Long or Batched Requests Fail

`max_input_length` is an approximate **character** budget for each input, not an exact token limit. For context-length errors, HTTP 400 responses, oversized requests, or rate limits, reduce `max_input_length` or `max_batch_size` first. A larger cache also consumes more memory and disk space.

## Configuration Parameters

The configuration lives at `running.reme_light_memory_config.embedding_model_config` in `agent.json`.

### Backends

| `backend`              | Credentials and endpoint                | Notes                                                                                             |
| ---------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `openai`               | `api_key` required; optional `base_url` | OpenAI and OpenAI-compatible text embedding services; the only backend that uses `use_dimensions` |
| `dashscope`            | `api_key` required                      | The model name selects the text or multimodal API path; QwenPaw currently sends only text         |
| `dashscope_multimodal` | `api_key` required                      | Uses the same adapter as `dashscope`; does not automatically read multimodal files                |
| `gemini`               | `api_key` required                      | Currently receives only text, does not expose `task_type`, and does not use `base_url`            |
| `ollama`               | No API key; `base_url` is the `host`    | Local or self-hosted text embedding service; the QwenPaw process must be able to reach it         |

### Fields

| Field              | Default    | Purpose                                                                      |
| ------------------ | ---------- | ---------------------------------------------------------------------------- |
| `backend`          | `"openai"` | SDK type used to call the service                                            |
| `api_key`          | `""`       | Service credential; unused by Ollama                                         |
| `base_url`         | `""`       | OpenAI API endpoint or Ollama host                                           |
| `model_name`       | `""`       | Model name; required for every backend                                       |
| `dimensions`       | `1024`     | Actual model output size, used for strict validation and index compatibility |
| `use_dimensions`   | `false`    | `openai` only; whether to send the dimension parameter                       |
| `enable_cache`     | `true`     | Whether to cache vectors for identical text                                  |
| `max_cache_size`   | `10000`    | Maximum number of local cache entries                                        |
| `max_input_length` | `8192`     | Approximate character budget per input                                       |
| `max_batch_size`   | `10`       | Maximum items ReMeLight submits per batch                                    |

Example for an OpenAI-compatible service:

```json
{
  "running": {
    "reme_light_memory_config": {
      "embedding_model_config": {
        "backend": "openai",
        "api_key": "your-api-key",
        "base_url": "https://your-embedding-service.example.com/v1",
        "model_name": "your-embedding-model",
        "dimensions": 1024,
        "use_dimensions": false,
        "enable_cache": true,
        "max_cache_size": 10000,
        "max_input_length": 8192,
        "max_batch_size": 10
      }
    }
  }
}
```

QwenPaw uses up to three retries during normal operation. The test uses one retry and a 15-second timeout. AgentScope may split requests again to meet provider limits, so `max_batch_size` is an upstream limit; the usable value still depends on the model and service.

## Related Pages

- [Long-term Memory](./memory) — Memory files, indexing, and retrieval
- [Memory-Evolving & Proactive Interaction](./memory-evolving-and-proactive) — Auto Memory, Auto Dream, Auto Memory Search, and Proactive workflows
- [Configuration & Working Directory](./config) — Agent configuration files and workspace layout
