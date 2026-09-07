"""Rate limiting for public endpoints (slowapi). Keys are client addresses kept in memory only —
they are never written to logs or the database."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
