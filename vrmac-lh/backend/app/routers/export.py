"""/api/export — implemented in the build workflow. See docs/api-contract.md for the agreed endpoints."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/export", tags=["export"])
