# OpenWond Draw Tool Plugin 🎨

Image generation for QwenPaw agents via OpenWond relay.

## Supported Models

| Model | Credits | Quality | Use Case |
|:---|:---:|:---:|:---|
| `gpt-image-2` | 4 | 🥇 Highest | Epic posters, art, cinematic |
| `nano-banana-v2` | 4 | 🥈 Good | Fast generation, fallback |
| `nano-banana-pro` | 6 | 🥇 Premium | Better Nano Banana quality |

## ⏱️ Timeout

**Default: 900 seconds.** GPT Image 2 is slow but worth the wait.

If it times out, retry with `model="nano-banana-v2"` for a faster result.

## Configuration

1. Install the plugin
2. Go to Agent Settings → Tools → `generate_image_openwond`
3. Click Configure
4. Enter your OpenWond API Key
5. Save and enable

## Usage

Once configured, the agent can generate images automatically:

```python
# GPT Image 2 (default, best quality)
result = await generate_image_openwond(
    prompt="Epic cinematic poster of a divine dragon",
)

# Nano Banana (faster fallback)
result = await generate_image_openwond(
    prompt="A cute cat in a wizard hat",
    model="nano-banana-v2",
    resolution="1K",
)
```

Or just tell the agent: "Generate an image of..." and it will call the tool.
