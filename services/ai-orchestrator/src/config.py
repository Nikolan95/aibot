import os


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


MONGO_URI = env("MONGO_URI", "mongodb://mongo:27017/aibot")
MONGO_DB = env("MONGO_DB", "aibot")
RABBITMQ_URL = env("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")

INCOMING_QUEUE = env("RABBITMQ_INCOMING_QUEUE", "message_received")
OUTGOING_QUEUE = env("RABBITMQ_OUTGOING_QUEUE", "wa_send")

CONTEXT_MESSAGE_LIMIT = int(env("CONTEXT_MESSAGE_LIMIT", "20"))
LOCK_TTL_MS = int(env("LOCK_TTL_MS", "30000"))

HUMANIZE_DELAY_MS_MIN = int(env("HUMANIZE_DELAY_MS_MIN", "350"))
HUMANIZE_DELAY_MS_MAX = int(env("HUMANIZE_DELAY_MS_MAX", "900"))

VIN_CHECK_URL = env("VIN_CHECK_URL", "https://vin.partificial.ai/api/vin/check")
VIN_CHECK_TIMEOUT_S = float(env("VIN_CHECK_TIMEOUT_S", "12"))

PARTS_SEARCH_URL = env("PARTS_SEARCH_URL", "https://part.partificial.ai/api/parts/search")
PARTS_SEARCH_TIMEOUT_S = float(env("PARTS_SEARCH_TIMEOUT_S", "20"))
