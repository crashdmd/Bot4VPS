ADD_SERVER_STATE = {}
EDIT_SERVER_STATE = {}
ADD_GROUP_STATE = {}
ADD_GROUP_SSL_STATE = {}

SCRIPT_RUN_STATE = {}
SCRIPT_CONFIRM_STATE = {}
PENDING_SERVER_CHANGES = {}
SSL_SETUP_STATE = {}
KEY_CREATE_STATE = {}
KEY_RENAME_STATE = {}
KEY_REPLACE_STATE = {}
KEY_PASTE_NEW_STATE = {}

SERVICE_INSTALL_STATE = {}
SVC_PROFILE_ADD_STATE = {}

# Docker (Telegram UI)
# Пошаговый мастер запуска контейнера: user_id → {step, server, image, name, ports[], env[], restart}
DOCKER_RUN_WIZARD = {}
# Ожидание Compose-файла (YAML/ZIP) от пользователя: user_id → {stage, name}
DOCKER_COMPOSE_UPLOAD = {}
# Короткие токены для длинных значений в callback_data (лимит Telegram — 64 байта):
# user_id → {token: value}. Нужен для deployment key внешних Compose-проектов.
DOCKER_CB_TOKENS = {}