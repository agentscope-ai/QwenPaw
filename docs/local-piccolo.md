# Local Piccolo decisions

Piccolo uses QwenPaw's native Jev decision interface for tool review and ReMe context compaction. Models are available on [Hugging Face](https://huggingface.co/agentscope-ai) (`agentscope-ai/Piccolo-*`) and [ModelScope](https://modelscope.cn/organization/AgentScope) (`AgentScope/Piccolo-*`). GGUF variants use `-BF16`, `-Q8_0`, and `-Q4_K_M` repositories. The catalog recommends BF16 and Q8_0 models according to machine memory; Q4_K_M is available through custom model download.

## Download and enable

1. In **Models → QwenPaw Local**, install or update the inference engine. The managed runtime supports both Flash chat and Piccolo decisions.
2. Choose **Hugging Face** or **ModelScope**, download a model under **Decision models**, and click **Start**. Check **Models → Default models → Decision model**.
3. For tool review, choose **Decision Model Mode** in the agent's security settings and enable review in the conversation.
4. For compaction, enable context compaction and **Decision model compaction** in the agent's context settings.

Both model groups share one managed runtime. Starting another local model switches that runtime to the selected model. Piccolo fills the decision slot; Flash fills the chat slot. Other providers' default selections remain unchanged.

## Runtime builds and releases

[`runtime-release.json`](../src/qwenpaw/local_models/runtime-release.json) pins the llama.cpp revision, the [Piccolo patch](patches/piccolo-llama.cpp.patch), and the installer release. The build matrix covers macOS and Linux on x64/ARM64, Windows CPU on x64/ARM64, and Windows x64 with CUDA 12.4/13.1.

Build and test a bundle locally:

```bash
python -m pip install cmake ninja
python scripts/piccolo_runtime.py build --target macos-arm64
python scripts/test_piccolo_runtime.py \
  --archive dist/piccolo-runtime/llama-piccolo-v1-bin-macos-arm64.tar.gz \
  --flash /path/to/Flash.gguf --piccolo /path/to/Piccolo.gguf \
  --gpu-layers auto
```

Windows builds run in a Visual Studio developer shell; ARM64 also requires LLVM. The smoke test runs Flash chat, Piccolo decisions, then Flash again using the packaged files.

The **Piccolo runtime** workflow builds and tests every platform. A `llama-cpp-<release>` tag (for example, `llama-cpp-piccolo-v1`) publishes the bundles to QwenPaw's download service using the existing OSS credentials. Publish from the reviewed commit before merging the installer update. The PR check **Runtime available for installer** verifies that every package is available at the configured URL.

The installer verifies the archive checksum and release identity before replacing the runtime, and restores the previous installation if the replacement fails. Model files are kept separately.

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
