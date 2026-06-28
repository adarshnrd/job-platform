"""Session health check — plain function invoked by APScheduler."""
import asyncio
from loguru import logger
from services.sessions.service import SessionService


def run_session_health_checks():
    """Validate all active sessions not checked in the last 12 hours."""
    logger.info("Starting scheduled session health checks...")
    service = SessionService()
    stats = asyncio.run(service.health.run_scheduled_health_checks())
    logger.info(f"Session health checks complete: {stats}")
    return stats
