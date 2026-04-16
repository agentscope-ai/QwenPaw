# Alibaba IdeaLab Provider Plugin

Alibaba IdeaLab LLM provider integration for CoPaw.

## Installation

```bash
copaw plugin install examples/plugins/idealab-provider
```

## Configuration

### 1. Get your API key

Visit: https://idealab.alibaba-inc.com/ideaTalk#/aistudio/manage/personalResource

### 2. Configure in `~/.copaw/config.json`

```json
{
  "agents": {
    "default": {
      "model": {
        "provider": "idealab",
        "model_name": "qwen3.6-plus",
        "api_key": "your-api-key-here"
      }
    }
  }
}
```

## Supported Models

| Model ID | Name | Multimodal | Description |
|----------|------|------------|-------------|
| `qwen3-coder-plus` | Qwen3 Coder Plus | ❌ | Specialized coding model |
| `qwen3.6-plus` | Qwen 3.6 Plus | ✅ | Latest Qwen model with multimodal support |
| `pitaya-03-20` | Pitaya 03-20 | ✅ | Advanced multimodal model with image support |

## Usage

After installation and configuration, simply use CoPaw as normal:

```bash
# Start chat
copaw chat

# The IdeaLab provider will be used automatically
```

### Example Configuration for Different Models

#### Qwen3 Coder Plus (Recommended for Coding)
```json
{
  "agents": {
    "default": {
      "model": {
        "provider": "idealab",
        "model_name": "qwen3-coder-plus",
        "api_key": "your-api-key"
      }
    }
  }
}
```

#### Qwen 3.6 Plus (Latest)
```json
{
  "agents": {
    "default": {
      "model": {
        "provider": "idealab",
        "model_name": "qwen3.6-plus",
        "api_key": "your-api-key"
      }
    }
  }
}
```

#### Pitaya 03-20 (Multimodal)
```json
{
  "agents": {
    "default": {
      "model": {
        "provider": "idealab",
        "model_name": "pitaya-03-20",
        "api_key": "your-api-key"
      }
    }
  }
}
```

## Troubleshooting

### Plugin not loading

Check the logs:
```bash
tail -f ~/.copaw/copaw.log
```

### API key issues

1. Verify your API key is correct
2. Ensure you have access to IdeaLab services
3. Check network connectivity to `idealab.alibaba-inc.com`

### Model not found

Make sure you're using one of the supported model IDs listed above.

## Support

For issues and questions:
- Check logs: `~/.copaw/copaw.log`
- GitHub Issues: https://github.com/your-org/copaw/issues

## License

MIT License
