"""Backward-compat shim — all AI logic now lives in services/ai/ package."""
from services.ai import *  # noqa: F401, F403
from services.ai.provider import _parse_json_response  # noqa: F401
