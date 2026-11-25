"""Node classification shared by storage, UI and execution boundaries."""
from __future__ import annotations


def is_gateway(node: dict) -> bool:
    return node.get("node_type") == "openwrt"


def require_linux(node: dict) -> dict:
    if is_gateway(node):
        raise ValueError("Это шлюз OpenWrt. Используйте раздел «Шлюзы».")
    return node


def load_linux_servers() -> list[dict]:
    from core.storage import load_servers
    return [node for node in load_servers() if not is_gateway(node)]


def load_gateways() -> list[dict]:
    from core.storage import load_servers
    return [node for node in load_servers() if is_gateway(node)]
