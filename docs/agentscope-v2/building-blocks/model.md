# Model

> Source:
> - https://docs.agentscope.io/v2/building-blocks/model.md

## Overview

The AgentScope (v2 / installed package `agentscope 1.0.20`) model layer is organized as a **two-tier hierarchy**:

1. A **Credential** at the top — carries the API authentication fields a provider requires (`api_key`, `base_url`, ...).
2. The model families a provider exposes beneath it — **Chat Model**, **TTS**, **Embedding**, and **Realtime Model**.

Hierarchy tree (from docs):

```
Credential
└── ChatModelBase
    ├── OpenAIChatModel
    ├── AnthropicChatModel
    ├── DashScopeChatModel
    └── ...
└── TTSModelBase (coming soon)
└── EmbeddingModelBase (coming soon)
└── RealtimeModelBase (coming soon)
```

From a credential, you can retrieve the list of available models for each model family the provider supports. This layering mirrors the natural frontend flow — register a credential first, then pick a model from under it — letting the UI authenticate once and surface every model family the provider supports.

**Currently shipped:** only the Chat Model family is implemented. **TTS, Embedding, and Realtime Model are "coming soon"** (being migrated from v1.0 to v2.0). Do NOT assume `TTSModelBase`, `EmbeddingModelBase`, or `RealtimeModelBase` are available for use.

## API Reference

### Chat Model classes (shipped)

A **Chat Model** is the LLM that drives an agent's conversation and tool calls, accepting and producing multimodal content beyond plain text. AgentScope currently ships:

| Provider           | Model Class           | Highlights                                                                 |
| ------------------ | --------------------- | -------------------------------------------------------------------------- |
| OpenAI             | `OpenAIChatModel`     | Chat Completions API, compatible with vLLM and OpenAI-compatible endpoints |
| OpenAI (Responses) | `OpenAIResponseModel` | Responses API with native reasoning support (o3, o4-mini)                  |
| Anthropic          | `AnthropicChatModel`  | Claude models with extended thinking and prompt caching                    |
| DashScope          | `DashScopeChatModel`  | Qwen models, multimodal (vision/audio/video), reasoning                    |
| DeepSeek           | `DeepSeekChatModel`   | OpenAI-compatible with prompt cache hit tokens                             |
| Gemini             | `GeminiChatModel`     | Google Gemini models with multimodal support                               |
| Moonshot           | `MoonshotChatModel`   | Kimi models (OpenAI-compatible)                                            |
| xAI                | `XAIChatModel`        | Grok models with native reasoning effort                                   |
| Ollama             | `OllamaChatModel`     | Local LLM hosting, credential is optional                                  |

Import paths used in the docs:
- Chat models: `from agentscope.model import <Class>` (e.g. `OpenAIChatModel`, `DashScopeChatModel`, `AnthropicChatModel`).
- Base classes / responses: `from agentscope.model import ChatModelBase, ChatResponse`.
- Credentials: `from agentscope.credential import <Class>` (e.g. `DashScopeCredential`, `OpenAICredential`, `CredentialBase`).
- Formatters: `from agentscope.formatter import FormatterBase, OpenAIChatFormatter, OpenAIMultiAgentFormatter`.
- Messages: `from agentscope.message import Msg, UserMsg`.
- Tool types: `from agentscope.tool import ToolChoice`.

### Chat Model constructor (common arguments)

Every chat model takes a credential, a model name, and an optional provider-specific `Parameters` object. Common constructor arguments shared by every chat model:

| Argument       | Type                    | Description                                                                                  |
| -------------- | ----------------------- | -------------------------------------------------------------------------------------------- |
| `credential`   | `CredentialBase`        | Provider-specific credential                                                                 |
| `model`        | `str`                   | Model identifier (e.g. `"qwen-plus"`)                                                        |
| `parameters`   | `Parameters \| None`    | Provider-specific parameters such as `temperature`, `thinking_enable`, `parallel_tool_calls` |
| `stream`       | `bool`                  | Whether to stream output                                                                     |
| `max_retries`  | `int`                   | Maximum API retries on failure                                                               |
| `context_size` | `int`                   | Context window used for context compression                                                  |
| `formatter`    | `FormatterBase \| None` | Override message formatter                                                                   |

Note: each provider class exposes its own nested `Parameters` class (e.g. `DashScopeChatModel.Parameters(...)`). Pass an instance via the `parameters=` argument; do not pass loose kwargs like `temperature=` directly to the constructor.

### `__call__` (invoke the model)

```python
async def __call__(
    self,
    messages: list[Msg],
    tools: list[dict] | None = None,
    tool_choice: ToolChoice | None = None,
    **kwargs: Any,
) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
```

Invoke the model by calling it with a list of `Msg` objects, plus optional `tools` and `tool_choice`. It is async — you must `await model(msgs)`.

**Parameters**

| Parameter     | Type                  | Default | Meaning                                            |
| ------------- | --------------------- | ------- | -------------------------------------------------- |
| `messages`    | `list[Msg]`           | —       | Conversation messages to send                      |
| `tools`       | `list[dict] \| None`  | `None`  | Tool/function definitions                          |
| `tool_choice` | `ToolChoice \| None`  | `None`  | Tool-selection control                             |
| `**kwargs`    | `Any`                 | —       | Extra provider-specific call args                  |

**Returns** — follows the model's `stream` setting:
- **`stream=False`** — awaits a single `ChatResponse` carrying the full output.
- **`stream=True`** — awaits an `AsyncGenerator[ChatResponse, None]`. Intermediate chunks (`is_last=False`) carry only the **delta** generated in that step. AgentScope appends one final chunk with `is_last=True` that carries the **full accumulated content**, so callers don't have to accumulate deltas themselves.

`ChatResponse` carries content blocks (`TextBlock`, `ThinkingBlock`, `ToolCallBlock`, `DataBlock`), an `is_last` flag, and a `ChatUsage` recording token counts and elapsed time.

### `generate_structured_output`

```python
response = await model.generate_structured_output(
    messages=[...],            # list[Msg]
    structured_model=MyModel,  # Pydantic BaseModel subclass or JSON schema
)
```

When you need a JSON object that conforms to a Pydantic model or JSON schema, call `generate_structured_output` instead of `__call__`. It returns a `StructuredResponse` whose `content` is a validated dict matching the schema.

**Parameters**

| Parameter          | Type                  | Meaning                                          |
| ------------------ | --------------------- | ------------------------------------------------ |
| `messages`         | `list[Msg]`           | Conversation messages                            |
| `structured_model` | Pydantic model / schema | Target schema the output must conform to       |

**Returns:** `StructuredResponse`; `.content` is a validated dict matching the schema.

Mechanism (from docs Info box): "`generate_structured_output` synthesizes a forced tool call from the schema, then validates and repairs the model's response."

### Formatter

A **formatter** translates AgentScope's `Msg` objects into the `list[dict]` payload that each provider's API expects. Configured via the optional `formatter` argument on the chat model constructor. Every provider ships two built-in variants:

| Variant                     | Use Case                                                                                                                                                                                                            |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ChatFormatter** (default) | Standard single-agent dialog. Each `Msg` maps 1:1 to an API message, preserving native roles (`user`, `assistant`, `system`).                                                                                       |
| **MultiAgentFormatter**     | Multi-agent scenarios such as debate or moderation. Consecutive agent messages are grouped and wrapped in `<history>` tags with the sender's name, while tool call / result sequences keep their native API format. |

Provider-specific concrete classes follow the pattern `<Provider>ChatFormatter` and `<Provider>MultiAgentFormatter` (e.g. `OpenAIChatFormatter`, `OpenAIMultiAgentFormatter`). For non-standard payload shapes, subclass `FormatterBase` and pass an instance through the same `formatter` argument.

### `list_models()` (classmethod)

Available on both credential classes and chat model classes.

```python
cards = DashScopeCredential.list_models()   # via credential class
cards = AnthropicChatModel.list_models()    # directly on model class
cards = MyProviderChatModel.list_models(custom_yaml_dir="/path/to/cards")
```

**Returns:** `list[ModelCard]`.

**Parameters**

| Parameter         | Type  | Default | Meaning                                                                 |
| ----------------- | ----- | ------- | ----------------------------------------------------------------------- |
| `custom_yaml_dir` | `str` | (model's own `_models/` dir) | Load model cards from a custom location instead of the default `_models/` directory |

Internally, `CredentialBase.list_models()` delegates to its linked `ChatModelBase` subclass (obtained via `get_chat_model_class()`), which loads YAML card definitions from its `_models/` directory.

### `get_chat_model_class()` (classmethod on Credential)

```python
model_cls = DashScopeCredential.get_chat_model_class()  # -> DashScopeChatModel
cards = model_cls.list_models()                          # -> list[ModelCard]
```

Returns the corresponding `ChatModelBase` subclass for a credential. Must be implemented when defining a custom credential.

### `ModelCard`

`ModelCard` is a declarative description of a model's capabilities and constraints, designed to drive the frontend (model selectors, parameter forms, feature toggles) dynamically without hardcoding provider-specific knowledge.

Fields:

| Field                  | Type                                   | Description                                                                                                                                |
| ---------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `name`                 | `str`                                  | Model identifier (e.g. `"claude-sonnet-4-6"`)                                                                                              |
| `label`                | `str`                                  | Human-readable display name (e.g. `"Claude Sonnet 4.6"`)                                                                                   |
| `status`               | `"active" \| "deprecated" \| "sunset"` | Model lifecycle status                                                                                                                     |
| `input_types`          | `list[str]`                            | Accepted input MIME types — used by the frontend to filter attachment uploads                                                              |
| `output_types`         | `list[str]`                            | Output MIME types the model can produce — advertises capabilities such as a thinking toggle when `application/x-thinking` is present       |
| `context_size`         | `int`                                  | Maximum context window in tokens                                                                                                           |
| `output_size`          | `int`                                  | Maximum output tokens                                                                                                                      |
| `parameter_schema`     | `dict`                                 | Final JSON Schema for the parameter form — base schema merged with per-model overrides                                                     |
| `parameters_overrides` | `dict[str, dict]`                      | The raw per-model overrides, before merging                                                                                                |

MIME types used by `input_types` / `output_types`:

| MIME Type                                  | Meaning                      |
| ------------------------------------------ | ---------------------------- |
| `text/plain`                               | Text                         |
| `application/x-thinking`                   | Reasoning / chain-of-thought |
| `image/*` (e.g. `image/png`, `image/jpeg`) | Image                        |
| `audio/*` (e.g. `audio/wav`, `audio/mp3`)  | Audio                        |
| `video/*` (e.g. `video/mp4`)               | Video                        |

## Configuration

### Chat model constructor options

| Option         | Type                    | Notes                                                            |
| -------------- | ----------------------- | --------------------------------------------------------------- |
| `credential`   | `CredentialBase`        | Required; provider-specific credential                          |
| `model`        | `str`                   | Required; model identifier                                      |
| `parameters`   | `Parameters \| None`    | Provider-specific nested `Parameters` instance                  |
| `stream`       | `bool`                  | Whether to stream output (controls `__call__` return type)      |
| `max_retries`  | `int`                   | Max API retries on failure                                      |
| `context_size` | `int`                   | Context window used for context compression                     |
| `formatter`    | `FormatterBase \| None` | Override message formatter                                       |

### Example provider `Parameters` fields (from docs examples)

- `DashScopeChatModel.Parameters`: `parallel_tool_calls: bool`, `thinking_enable: bool`, `thinking_budget: int`.
- Custom example `Parameters`: `max_tokens: int | None = Field(default=None, gt=0)`, `temperature: float | None = Field(default=None, ge=0, le=2)`.

### Credential fields (from custom example)

| Field      | Type        | Default                          | Notes                          |
| ---------- | ----------- | -------------------------------- | ------------------------------ |
| `type`     | `Literal[...]` | unique discriminator string   | Required discriminator         |
| `api_key`  | `SecretStr` | —                                | API key                        |
| `base_url` | `str`       | provider default URL             | API base URL                   |

### Model card YAML fields

| Field                 | Type                | Notes                                                       |
| --------------------- | ------------------- | ----------------------------------------------------------- |
| `name`                | `str`               | Model identifier                                            |
| `label`               | `str`               | Display name                                                |
| `status`              | `active\|deprecated\|sunset` | Lifecycle status                                  |
| `input_types`         | `list[str]`         | Input MIME types                                            |
| `output_types`        | `list[str]`         | Output MIME types                                           |
| `context_size`        | `int`               | Max context window (tokens)                                 |
| `output_size`         | `int`               | Max output tokens                                           |
| `parameter_overrides` | `dict[str, dict]`   | Per-model parameter overrides (merged onto base schema)     |

### Parameter override syntax (YAML `parameter_overrides`)

| Override syntax           | Effect                                                                  |
| ------------------------- | ----------------------------------------------------------------------- |
| `param: { ... }`          | Shallow-merge into the base field (e.g. `max_tokens: {maximum: 16384}`) |
| `param: { hidden: true }` | Hide the parameter from the frontend                                    |
| `param: null`             | Remove the parameter entirely                                           |

`parameter_schema` exposed to the frontend is built in two layers:
1. **Base schema** — auto-derived from the chat model's `Parameters` class via `model_json_schema()`.
2. **Per-model overrides** — the YAML's `parameter_overrides` block is merged on top, field by field.

## Usage Patterns

### Create a streaming chat model

```python
import os
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

model = DashScopeChatModel(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="qwen-plus",
    stream=True,
)
```

### Create a chat model with tool parameters

```python
import os
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

model = DashScopeChatModel(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="qwen-plus",
    stream=False,
    parameters=DashScopeChatModel.Parameters(
        parallel_tool_calls=False,
    ),
)
```

### Create a reasoning chat model

```python
import os
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

model = DashScopeChatModel(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="qwen3-235b-a22b-thinking-2507",
    parameters=DashScopeChatModel.Parameters(
        thinking_enable=True,
        thinking_budget=2048,
    ),
)
```

### Call a streaming chat model (delta-then-accumulated)

```python
import asyncio
import os
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg

async def main():
    model = DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-plus",
        stream=True,
    )
    msgs = [UserMsg(name="user", content="Count from 1 to 5.")]

    async for chunk in await model(msgs):
        if chunk.is_last:
            print("Final:", chunk.content)   # full accumulated content
        else:
            print("Delta:", chunk.content)   # delta only

asyncio.run(main())
```

Representative streaming trace:

```
Delta: [TextBlock(text='1')]
Delta: [TextBlock(text=', 2,')]
Delta: [TextBlock(text=' 3, ')]
Delta: [TextBlock(text='4, 5')]
Final: [TextBlock(text='1, 2, 3, 4, 5')]
```

### Generate structured output

```python
import asyncio
import os
from pydantic import BaseModel
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg

class WeatherInfo(BaseModel):
    city: str
    temperature: float
    unit: str

async def main():
    model = DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-plus",
        stream=False,
    )
    response = await model.generate_structured_output(
        messages=[UserMsg(name="user", content="What's the weather in Shanghai?")],
        structured_model=WeatherInfo,
    )
    print(response.content)  # validated dict matching WeatherInfo

asyncio.run(main())
```

### Switch to the multi-agent formatter

```python
import os
from agentscope.model import OpenAIChatModel
from agentscope.credential import OpenAICredential
from agentscope.formatter import OpenAIMultiAgentFormatter

model = OpenAIChatModel(
    credential=OpenAICredential(api_key=os.environ["OPENAI_API_KEY"]),
    model="gpt-4.1",
    formatter=OpenAIMultiAgentFormatter(),
)
```

No agent code changes are required to switch formatter modes.

### Custom provider — Step 1: define the credential

```python
from typing import Literal, Type, TYPE_CHECKING
from pydantic import ConfigDict, Field, SecretStr
from agentscope.credential import CredentialBase

if TYPE_CHECKING:
    from agentscope.model import ChatModelBase

class MyProviderCredential(CredentialBase):
    model_config = ConfigDict(title="My Provider API")
    type: Literal["my_provider_credential"] = "my_provider_credential"

    api_key: SecretStr = Field(description="API key for My Provider.")
    base_url: str = Field(default="https://api.myprovider.com/v1")

    @classmethod
    def get_chat_model_class(cls) -> Type["ChatModelBase"]:
        from .my_model import MyProviderChatModel
        return MyProviderChatModel
```

### Custom provider — Step 2: implement the chat model

```python
from typing import Literal, Any, AsyncGenerator
from pydantic import BaseModel, Field
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.message import Msg
from agentscope.tool import ToolChoice
from agentscope.formatter import FormatterBase, OpenAIChatFormatter

class MyProviderChatModel(ChatModelBase):
    class Parameters(BaseModel):
        max_tokens: int | None = Field(default=None, gt=0)
        temperature: float | None = Field(default=None, ge=0, le=2)

    type: Literal["my_provider_chat"] = "my_provider_chat"

    def __init__(
        self,
        credential: "MyProviderCredential",
        model: str,
        parameters: Parameters | None = None,
        stream: bool = True,
        max_retries: int = 3,
        context_size: int = 128000,
        formatter: FormatterBase | None = None,
    ) -> None:
        super().__init__(
            credential=credential,
            model=model,
            parameters=parameters or self.Parameters(),
            stream=stream,
            max_retries=max_retries,
            context_size=context_size,
        )
        # If your API follows the OpenAI format, reuse OpenAIChatFormatter;
        # otherwise implement your own FormatterBase subclass.
        self.formatter = formatter or OpenAIChatFormatter()

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        formatted_messages = await self.formatter.format(messages)
        # Call your provider's API using self.credential.api_key, etc.
        ...
```

### Custom provider — Step 3: add model cards (optional)

Drop YAML files into a `_models/` directory next to your model implementation:

```yaml
name: my-model-v1
label: My Model V1
status: active
input_types:
  - text/plain
output_types:
  - text/plain
context_size: 128000
output_size: 4096
parameter_overrides:
  max_tokens: {"maximum": 4096}
```

`MyProviderChatModel.list_models()` then loads every YAML in that directory. To pull cards from a different location, pass `custom_yaml_dir`:

```python
cards = MyProviderChatModel.list_models(custom_yaml_dir="/path/to/cards")
```

### Retrieve model cards (frontend integration)

```python
from agentscope.credential import DashScopeCredential
from agentscope.model import AnthropicChatModel

# Via credential class
cards = DashScopeCredential.list_models()

# Or directly on the model class
cards = AnthropicChatModel.list_models()

for card in cards:
    print(f"{card.name}: context={card.context_size}, inputs={card.input_types}")
```

```python
model_cls = DashScopeCredential.get_chat_model_class()  # -> DashScopeChatModel
cards = model_cls.list_models()                          # -> list[ModelCard]
```

Example Claude model card YAML:

```yaml
name: claude-sonnet-4-6
label: Claude Sonnet 4.6
status: active

input_types:
  - text/plain
  - image/jpeg
  - image/png
  - image/gif
  - image/webp

output_types:
  - text/plain
  - application/x-thinking

context_size: 1000000
output_size: 65536

parameter_overrides:
  max_tokens: {"maximum": 65536}
```

## Gotchas & Version Notes

- **Two-tier hierarchy is mandatory.** You must construct a provider-specific `Credential` and pass it via `credential=` to the chat model. There is no flat "api_key=" constructor for chat models in v2 — auth lives on the credential object (e.g. `DashScopeCredential(api_key=...)`).
- **Provider params go through the nested `Parameters` class.** Pass `parameters=DashScopeChatModel.Parameters(temperature=..., thinking_enable=...)`, NOT loose kwargs on the model constructor. Each provider exposes its own `Parameters` schema.
- **Models are async.** `__call__` and `generate_structured_output` are coroutines — always `await`. For streaming, `await model(msgs)` returns the async generator, then iterate with `async for`.
- **Streaming semantics:** intermediate chunks (`is_last=False`) carry only the **delta**; the final chunk (`is_last=True`) carries the **full accumulated content**. Do not concatenate the final chunk on top of accumulated deltas — it already contains the whole content. Detect completion with `chunk.is_last`.
- **Use `generate_structured_output` for schema-bound JSON**, not `__call__`. It forces a tool call from the schema and validates/repairs the output; `.content` is a validated dict. Returns a `StructuredResponse`, not a `ChatResponse`.
- **Formatter selection matters for multi-agent.** Default `ChatFormatter` maps each `Msg` 1:1. For debate/moderation, use the provider's `MultiAgentFormatter` (e.g. `OpenAIMultiAgentFormatter`) which wraps consecutive agent messages in `<history>` tags with sender names. Swapping the formatter requires no agent code changes.
- **TTS / Embedding / Realtime Model are NOT available.** They are marked "coming soon" (migration from v1.0 to v2.0). `TTSModelBase`, `EmbeddingModelBase`, `RealtimeModelBase` should not be used in v2 code yet.
- **`OpenAIChatModel` vs `OpenAIResponseModel`:** `OpenAIChatModel` uses the Chat Completions API (also for vLLM / OpenAI-compatible endpoints); `OpenAIResponseModel` uses the Responses API with native reasoning support (o3, o4-mini). Pick the right one for reasoning models.
- **Ollama credential is optional** (local hosting) — unlike other providers which require a credential.
- **Custom credentials must implement `get_chat_model_class()`** and a unique `type` discriminator (Literal). Custom chat models must define a `Parameters` inner class and implement `_call_api` (note: `_call_api`, not `__call__` — the base class wires `__call__` to it).
- **`ChatResponse` content blocks:** `TextBlock`, `ThinkingBlock`, `ToolCallBlock`, `DataBlock`. Usage/timing live on `ChatUsage`.
- **Model card `parameter_overrides` semantics:** `param: {...}` shallow-merges, `param: {hidden: true}` hides the field, `param: null` removes it entirely. The final `parameter_schema` is the `Parameters` base schema (`model_json_schema()`) merged with these overrides.
- **`ModelCard.status`** is one of `"active"`, `"deprecated"`, `"sunset"` — treat `deprecated`/`sunset` models accordingly.
- **`list_models()` is a classmethod** available on both credential and model classes; `CredentialBase.list_models()` delegates to the linked chat model class via `get_chat_model_class()`. Use `custom_yaml_dir=` to load cards from a non-default location.
