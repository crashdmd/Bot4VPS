"""
Telegram UI handlers package.
Gradual split of monolithic bot_handlers.py
"""

from .key_handlers import process_key_callback, process_key_message
from .script_handlers import process_script_callback, process_script_message
from .auth_handlers import process_auth_callback
from .server_handlers import process_server_callback, process_server_message
from .admin_handlers import process_admin_callback
from .service_handlers import (
    process_service_callback,
    process_service_document,
    process_service_message,
)
from ui.telegram.task_ui import process_task_callback

__all__ = [
    "process_key_callback",
    "process_key_message",
    "process_script_callback",
    "process_script_message",
    "process_auth_callback",
    "process_server_callback",
    "process_server_message",
    "process_admin_callback",
    "process_service_callback",
    "process_service_document",
    "process_service_message",
    "process_task_callback",
]
