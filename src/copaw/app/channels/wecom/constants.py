# -*- coding: utf-8 -*-
"""WeCom channel constants."""

# Streaming message processing timeout (seconds)
STREAM_TIMEOUT = 360

# Max content length per stream frame (bytes), per WeCom official docs
MAX_STREAM_CONTENT_LENGTH = 20480

# Placeholder message while agent is thinking
THINKING_MESSAGE = "Thinking..."

# Group chat type identifier
CHAT_TYPE_GROUP = "group"

# Welcome message text
WELCOME_MESSAGE = "Hello! I'm CoPaw AI Assistant. How can I help you?"

# Timeout error message
TIMEOUT_MESSAGE = "Sorry, request timed out. Please try again."

# Processing error message
ERROR_MESSAGE = "Sorry, an error occurred while processing your request."
