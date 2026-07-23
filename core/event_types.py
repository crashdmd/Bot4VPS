from enum import Enum


class EventType(str, Enum):
    DATABASE = "database"
    SSL = "ssl"
    SSH = "ssh"
    SCRIPT = "script"
    SERVER = "server"
    KEY = "key"
    GENERAL = "general"


class EventLevel(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class EventReason(str, Enum):
    DATABASE_RESTORED = "database_restored"
    SSL_RENEWED = "ssl_renewed"
    SSL_EXPIRED = "ssl_expired"
    SERVER_ONLINE = "server_online"
    SERVER_OFFLINE = "server_offline"
