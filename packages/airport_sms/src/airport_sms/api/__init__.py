"""控制面 API。"""

from airport_sms.api.app import create_app
from airport_sms.api.health import health

__all__ = ["create_app", "health"]
