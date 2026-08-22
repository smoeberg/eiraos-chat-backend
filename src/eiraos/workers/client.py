from arq import create_pool
from arq.connections import RedisSettings
from eiraos.core.config import settings
import structlog

logger = structlog.get_logger()

async def get_arq_pool():
    """Create a Redis connection pool for ARQ job queue."""
    try:
        return await create_pool(RedisSettings(host="localhost", port=6379))
    except Exception as e:
        logger.error("Failed to connect to Redis for background jobs", error=str(e))
        return None
