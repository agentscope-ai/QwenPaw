# Local Piccolo decisions

Piccolo uses QwenPaw's native Jev decision interface for tool review and ReMe context compaction. The model repositories are `agentscope-ai/Piccolo-4B`, `agentscope-ai/Piccolo-9B`, and `agentscope-ai/Piccolo-27B` on Hugging Face. Their model cards and weights use Apache-2.0, matching the QwenPaw-Flash release convention. GGUF variants use separate `-BF16`, `-Q8_0`, and `-Q4_K_M` repositories. Built-in recommendations include BF16 and Q8_0 according to machine memory. For example, `agentscope-ai/Piccolo-9B-BF16` downloads the unquantized BF16 GGUF, while `agentscope-ai/Piccolo-9B-Q8_0` downloads the smaller Q8 variant. Q4_K_M model cards record the expanded synthetic numerical regression results and limitations.

## Download and enable

The local model selector separates **Chat models** and **Decision models** into independently scrollable sections. Both use the same managed runtime, which serves one model at a time. Repository IDs are shown as plain text; existing download and lifecycle controls are retained.

1. In **Models → Local models**, download the appropriate Piccolo GGUF and use the existing **Start** control. Starting Piccolo selects the decision model slot; it does not replace the default chat selection on another provider.
2. Check **Models → Default models → Decision model**. An agent-specific decision model can override the global selection.
3. For tool review, enable automatic review, select **Decision Model Mode** in the agent's security settings, and enable review in the conversation.
4. For compaction, enable context compaction and its separate **Decision model compaction** switch in the agent's context settings.

The existing fallback remains active when a decision fails. Starting the model does not turn on review or compaction. QwenPaw manages one llama.cpp model at a time; starting Piccolo replaces any chat model running in that same local runtime.

## Compatible runtime

This integration requires the companion [llama.cpp patch](patches/piccolo-llama.cpp.patch), based on upstream commit [`f4d8af608a6b39946406f9439edfb6e83ca6a923`](https://github.com/ggml-org/llama.cpp/commit/f4d8af608a6b39946406f9439edfb6e83ca6a923). It is not part of a released upstream binary yet. QwenPaw rejects a runtime that reports Piccolo as an ordinary text-generation model.

Build the runtime in a separate checkout:

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
git checkout f4d8af608a6b39946406f9439edfb6e83ca6a923
git apply /path/to/QwenPaw/docs/patches/piccolo-llama.cpp.patch
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_UI=OFF
cmake --build build --target llama-server llama-quantize test-piccolo-layout -j 6
```

Use the platform backend options from llama.cpp's build documentation when needed. Stop the managed local model, back up QwenPaw's local runtime, and install `llama-server` with its matching shared libraries into the existing runtime directory. Print its exact location from the QwenPaw Python environment:

```bash
python -c 'from qwenpaw.local_models.llamacpp import LlamaCppBackend; print(LlamaCppBackend().executable.parent)'
```

Then continue with the normal download and Start controls. There is no additional service URL or TypeSafe account to configure. Reinstalling an unpatched upstream runtime removes Piccolo support. Unmodified Ollama's chat API does not implement this inference contract.

## Inference contract

QwenPaw sends native questions and state through AgentScope's Jev classifier to the managed runtime's `/v1/systemone` endpoint. The transport disables request compression because stock llama.cpp HTTP builds do not include a zstd decoder. It does not generate or parse probability JSON through Chat Completions.

The repository name is Piccolo. The GGUF carries `qwen35.attention.causal=false`, serialized decision type `blink`, the tokenizer's prompt boundaries, and probability temperature 1.0. The runtime applies noncausal attention in Qwen3.5's full-attention layers; linear-attention layers keep their original recurrent computation. Each question uses the checkpoint's exact `flex_twice` layout, with thinking disabled and an `Answer: (` readout boundary. The repeated form is used when the request's one-pass token budget is at most 3,000 and every repeated row fits the checkpoint's context limit.

The runtime reads the logits of the single-token candidate labels directly. Softmax over those candidate logits at temperature 1 gives the candidate-normalized probabilities, equivalently renormalizing their token log probabilities. It generates no answer tokens. The existing SystemOne response supplies binary probabilities, choice distributions and confidence, or ordered scores. These distributions are not empirical calibration guarantees; task-quality and threshold calibration are separate evaluations.

QwenPaw uses one slot, equal context/batch/microbatch limits, no prompt cache, and no context shifting for Piccolo. This initial integration caps each complete question prompt at 8,192 tokens, including any repeated layout, independently of the larger shared chat-window setting. Requests that do not fit the complete-prompt budget fail explicitly. Reusing a causal prefix cache, splitting the prompt into causal chunks, or silently truncating it changes the computation.

## Checkpoint conversion and verification

Use the patched converter with the complete checkpoint and its `decision-inference.json`:

```bash
python convert_hf_to_gguf.py /path/to/Piccolo-4B --no-mtp --outtype bf16 --outfile Piccolo-4B-BF16.gguf
build/bin/llama-quantize Piccolo-4B-BF16.gguf Piccolo-4B-Q8_0.gguf Q8_0
```

The catalog includes both BF16 and Q8_0. Its display thresholds leave room for full-prompt attention and runtime buffers:

| Model size | Q8_0 minimum memory | BF16 minimum memory | BF16 download        |
| ---------- | ------------------- | ------------------- | -------------------- |
| 4B         | 16 GB               | 24 GB               | 8.42 GB / 2 shards   |
| 9B         | 24 GB               | 32 GB               | 17.92 GB / 4 shards  |
| 27B        | 48 GB               | 80 GB               | 53.81 GB / 12 shards |

These thresholds are catalog policy rather than measured peak-memory guarantees; context length and platform affect actual usage. Download every standard GGUF shard into the same model directory. BF16 keeps the checkpoint's main weight precision, with some normalization and recurrent-state tensors stored as F32 by the converter. It uses the same native decision slot, runtime capability check and review/compaction switches as Q8_0.

Q4_K_M is also published after an expanded synthetic regression of 265 requests / 556 judgments per model size; its measured probability differences and limitations are disclosed in each Q4 model card. These checks are not a benchmark or risk calibration.

All text backbone layers and the output projection are retained. MTP and the vision encoder are not used by this text decision path; the original Hugging Face checkpoint remains complete. Verify the BF16 conversion against the full Transformers reference first, then measure quantization error separately. The model repository includes the reference inference script and third-party license notice.

`test-piccolo-layout MODEL.gguf REQUEST.json` emits the actual runtime input and candidate token IDs for comparison with the checkpoint tokenizer; it uses vocabulary-only loading and is a formatter check, not an inference test.
