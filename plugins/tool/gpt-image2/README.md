# GPT Image 2 Tool Plugin

A QwenPaw tool plugin that enables image generation using OpenAI's GPT Image 2 model.

## Features

- Generate high-quality images from text prompts
- Support for multiple image sizes (1024x1024, 1024x1792, 1792x1024)
- Quality options: standard, hd
- Style options: natural, vivid
- Pure backend implementation - no frontend code required

## Installation

```bash
qwenpaw plugin install /path/to/gpt-image2
```

Or from ZIP:

```bash
qwenpaw plugin install gpt-image2-tool.zip
```

## Configuration

1. Start QwenPaw application
2. Navigate to Agent Settings → Tools
3. Find the `generate_image_gpt` tool (🎨 icon)
4. Click "Configure" button
5. Enter your OpenAI API Key (get it from https://platform.openai.com/api-keys)
6. Save configuration
7. Enable the tool

## Usage

Once configured and enabled, the Agent can automatically call this tool when asked to generate images:

**User**: Please generate an image of a serene mountain landscape at sunset

**Agent**: [Calls generate_image_gpt tool with appropriate parameters]

## Tool Parameters

### generate_image_gpt

Generate an image using OpenAI GPT Image 2 model.

**Parameters:**

- `prompt` (str, required): Text description of the image to generate
- `size` (str, optional): Image size, one of "1024x1024", "1024x1792", "1792x1024" (default: "1024x1024")
- `quality` (str, optional): Quality level, one of "standard", "hd" (default: "standard")
- `style` (str, optional): Image style, one of "natural", "vivid" (default: "natural")

**Returns:**

- ImageBlock with the generated image URL
- TextBlock with generation metadata

## Requirements

- QwenPaw >= 0.1.0
- httpx >= 0.24.0
- Valid OpenAI API key with access to GPT Image 2

## Pricing

GPT Image 2 usage is billed by OpenAI. See https://openai.com/pricing for current pricing.

## Troubleshooting

### Tool not showing up

- Ensure the plugin is installed: `qwenpaw plugin list`
- Check QwenPaw logs: `~/.qwenpaw/logs/qwenpaw.log`
- Restart QwenPaw after installation

### API errors

- Verify your API key is correct
- Check your OpenAI account has sufficient credits
- Ensure you have access to GPT Image 2 model

### Configuration not saving

- Check file permissions in `~/.qwenpaw/plugins/`
- Review logs for error messages

## Development

This is a pure backend plugin. To modify:

1. Edit `tool.py` for tool logic
2. Edit `plugin.py` for registration logic
3. Edit `plugin.json` for metadata
4. Reinstall with `--force` flag

## License

Same as QwenPaw

## Support

For issues and feature requests, please use the QwenPaw issue tracker.
