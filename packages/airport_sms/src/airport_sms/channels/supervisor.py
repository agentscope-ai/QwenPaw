"""通道子进程监督：子挂不影响宿主。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChannelChild:
    """通道子进程句柄（测试用内存模拟）。"""

    name: str
    alive: bool = True
    launches: int = 1


@dataclass
class ChannelSupervisor:
    """监督重启。过滤宿主凭证不传入子环境。"""

    children: dict[str, ChannelChild] = field(default_factory=dict)
    host_healthy: bool = True

    def start(self, name: str) -> ChannelChild:
        """启动子通道。"""
        child = ChannelChild(name=name)
        self.children[name] = child
        return child

    def kill(self, name: str) -> None:
        """杀死子进程。"""
        self.children[name].alive = False

    def ensure(self, name: str) -> ChannelChild:
        """若已死则重启。"""
        child = self.children.get(name)
        if child is None or not child.alive:
            child = ChannelChild(
                name=name,
                launches=(child.launches + 1) if child else 1,
            )
            self.children[name] = child
        return child

    def child_env(self, host_env: dict[str, str]) -> dict[str, str]:
        """过滤宿主密钥。"""
        blocked = {"AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "DATABASE_URL"}
        return {k: v for k, v in host_env.items() if k not in blocked}


__all__ = ["ChannelChild", "ChannelSupervisor"]
