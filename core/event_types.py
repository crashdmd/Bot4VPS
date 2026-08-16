from enum import Enum


class EventType(str, Enum):
    DATABASE = "database"
    SSL = "ssl"
    SSH = "ssh"
    SCRIPT = "script"
    SERVER = "server"
    KEY = "key"
    GENERAL = "general"
    TASK = "task"
    SERVICE = "service"
    UPDATE = "update"


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
    TASK_QUEUED = "task_queued"
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    TASK_QUEUE_PAUSED = "task_queue_paused"
    SERVICE_INSTALLED = "service_installed"
    SERVICE_REMOVED = "service_removed"
    SERVICE_SYNCED = "service_synced"
    SERVICE_UPDATE_AVAILABLE = "service_update_available"
    UPDATE_AVAILABLE = "update_available"
    UPDATE_INSTALLED = "update_installed"
    UPDATE_FAILED = "update_failed"
    ROLLBACK_DONE = "rollback_done"
    ROLLBACK_FAILED = "rollback_failed"
