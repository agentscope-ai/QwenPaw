# GPT Image 2 Tool Plugin

A QwenPaw tool plugin that enables image generation and editing using OpenAI's GPT Image 2 model.

## Features

- **Generate images** from text prompts
- **Edit/generate images** using reference images (1-16 images)
- Support for multiple image sizes (1024x1024, 1024x1536, 1536x1024, auto)
- Quality options: low, medium, high, auto
- High fidelity image processing (automatic for gpt-image-2)
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
3. Find the GPT Image 2 tools:
   - `generate_image_gpt` (🎨 icon) - Generate images from text
   - `edit_image_gpt` (🖼️ icon) - Edit images with reference images
4. Click "Configure" button for each tool
5. Enter your OpenAI API Key (get it from https://platform.openai.com/api-keys)
6. Save configuration
7. Enable the tools you want to use

## Usage

Once configured and enabled, the Agent can automatically call these tools when asked to generate or edit images.

### Example 1: Generate Image from Text

**User**: Please generate an image of a serene mountain landscape at sunset

**Agent**: [Calls generate_image_gpt tool with appropriate parameters]

### Example 2: Edit Image with Reference

**User**: I have a photo at /path/to/my/photo.jpg, please make it look like a watercolor painting

**Agent**: [Calls edit_image_gpt tool with reference image and prompt]

### Example 3: Generate from Multiple References

**User**: Use these product images to create a gift basket: image1.png, image2.jpg, https://example.com/image3.png

**Agent**: [Calls edit_image_gpt tool with multiple reference images]

## Tool Parameters

### generate_image_gpt

Generate an image using OpenAI GPT Image 2 model from text prompt only.

**Parameters:**

- `prompt` (str, required): Text description of the image to generate
- `size` (str, optional): Image size, one of "1024x1024", "1024x1792", "1792x1024" (default: "1024x1024")
- `quality` (str, optional): Quality level, one of "low", "medium", "high", "auto" (default: "auto")

**Returns:**

- ImageBlock with the generated image
- TextBlock with generation metadata

### edit_image_gpt

Edit or generate image using reference images with OpenAI GPT Image 2 model.

**Parameters:**

- `prompt` (str, required): Text description of the desired image edit or generation
- `reference_images` (List[str], required): List of 1-16 reference images. Each can be:
  - Local file path (e.g., `/path/to/image.png`, `./photo.jpg`)
  - Web URL (e.g., `https://example.com/image.png`)
  - Note: Local files are automatically converted to base64
- `size` (str, optional): Image size, one of "1024x1024", "1024x1536", "1536x1024", "auto" (default: "1024x1024")
- `quality` (str, optional): Quality level, one of "low", "medium", "high", "auto" (default: "auto")

**Note:** GPT Image 2 always processes images at high fidelity and does not support the `input_fidelity` parameter.

**Returns:**

- ImageBlock with the edited/generated image
- TextBlock with editing metadata

**Supported Image Formats:**

- PNG (.png)
- JPEG (.jpg, .jpeg)
- WebP (.webp)

## Requirements

- QwenPaw >= 1.1.6
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
