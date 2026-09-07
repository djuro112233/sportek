"""/api/listings — implemented in the build workflow. See docs/api-contract.md for the agreed endpoints."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/listings", tags=["listings"])
