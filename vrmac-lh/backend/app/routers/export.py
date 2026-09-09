"""/api/export — interoperability stub (NGSI-LD PointOfInterest + DCAT-AP).

Public, rate-limited, read-only. Reads go through the visitor DB role (row-level security limits
them to approved rows) *and* the explicit ``approved_only`` filter inside ``services.export``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_public_db
from ..ratelimit import limiter
from ..services import export as export_service

router = APIRouter(prefix="/api/export", tags=["export"])

JSON_LD = "application/ld+json"


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _validity_headers(keyvalues: list[dict]) -> dict[str, str]:
    errors = export_service.validate_entities(keyvalues)
    return {
        "X-Schema-Valid": "true" if not errors else "false",
        "X-Schema-Id": export_service.POI_SCHEMA_URI,
        "X-Schema-Version": export_service.schema_version(),
    }


@router.get(
    "/ngsi-ld",
    summary="Approved POIs as normalized NGSI-LD PointOfInterest entities",
    response_class=JSONResponse,
)
@limiter.limit(settings.rate_limit_public)
def ngsi_ld_normalized(request: Request, db: Session = Depends(get_public_db)) -> JSONResponse:
    """Normalized NGSI-LD list (``Property``/``GeoProperty`` attributes + ``@context``).

    Ready for ``POST /ngsi-ld/v1/entityOperations/upsert`` on an NGSI-LD context broker.
    """
    pairs = export_service.poi_entities(db, base_url=_base_url(request))
    headers = _validity_headers([kv for kv, _ in pairs])
    return JSONResponse([norm for _, norm in pairs], media_type=JSON_LD, headers=headers)


@router.get(
    "/ngsi-ld/keyvalues",
    summary="Approved POIs as NGSI-LD key-values entities (schema-validated)",
    response_class=JSONResponse,
)
@limiter.limit(settings.rate_limit_public)
def ngsi_ld_keyvalues(request: Request, db: Session = Depends(get_public_db)) -> JSONResponse:
    """Key-values form; ``X-Schema-Valid`` says whether every entity validates against the
    vendored Smart Data Models PointOfInterest schema."""
    keyvalues = [kv for kv, _ in export_service.poi_entities(db, base_url=_base_url(request))]
    return JSONResponse(keyvalues, media_type="application/json", headers=_validity_headers(keyvalues))


@router.get(
    "/dcat-ap",
    summary="DCAT-AP dataset description of the NGSI-LD export (JSON-LD)",
    response_class=JSONResponse,
)
@limiter.limit(settings.rate_limit_public)
def dcat_ap(request: Request, db: Session = Depends(get_public_db)) -> JSONResponse:
    doc = export_service.dcat_ap(db, base_url=_base_url(request))
    return JSONResponse(doc, media_type=JSON_LD)
