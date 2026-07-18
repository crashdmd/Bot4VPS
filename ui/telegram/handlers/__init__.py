"""
Telegram UI handlers package.
Gradual split of monolithic bot_handlers.py
"""

from .key_handlers import process_key_callback, process_key_message
from .script_handlers import process_script_callback, process_script_message
from .auth_handlers import process_auth_callback
from .server_handlers import process_server_callback, process_server_message
from .admin_handlers import process_admin_callback
