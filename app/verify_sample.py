"""
GET /api/v1/verify-sample/{sample_id}

Lets another app check whether a Golden / Shipment / Development sample ID
exists in this system. Returns existence only -- no sample data.

    valid   -> {"sample_id": "GLD-7K3M9Q2XPA", "valid": true,  "status": "valid",   "sample_type": "golden"}
    invalid -> {"sample_id": "GLD-XXXXXXXXXX", "valid": false, "status": "invalid", "sample_type": null}

Always HTTP 200 for a well-formed request, so the caller only has to read `valid`.

Optional API key: if the SAMPLE_VERIFY_API_KEY environment variable is set, the
caller must send it in an `X-API-Key` header (401 otherwise). If it is not set,
the endpoint is open.

Place this file next to models.py (in the `app` package) and register it in
main.py:

    from .verify_sample import router as verify_sample_router
    app.include_router(verify_sample_router)
"""
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    GoldenSample, ShipmentSample, DevelopmentSample,
    GOLDEN_ID_PREFIX, SHIPMENT_ID_PREFIX, DEV_ID_PREFIX,
)

router = APIRouter(prefix="/api/v1", tags=["verify"])

# prefix -> (sample_type label, model, ID column)
_LOOKUP = {
    GOLDEN_ID_PREFIX: ("golden", GoldenSample, GoldenSample.golden_id),
    SHIPMENT_ID_PREFIX: ("shipment", ShipmentSample, ShipmentSample.shipment_id),
    DEV_ID_PREFIX: ("development", DevelopmentSample, DevelopmentSample.dev_id),
}


def _check_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("SAMPLE_VERIFY_API_KEY")
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@router.get("/verify-sample/{sample_id}", dependencies=[Depends(_check_api_key)])
def verify_sample(sample_id: str, db: Session = Depends(get_db)):
    normalized = sample_id.strip().upper()
    prefix = normalized.split("-", 1)[0]
    entry = _LOOKUP.get(prefix)

    exists = False
    sample_type = None
    if entry:
        label, _model, column = entry
        # The prefix tells us which table to look in -- one indexed lookup.
        exists = db.query(column).filter(column == normalized).first() is not None
        sample_type = label if exists else None

    return {
        "sample_id": sample_id,
        "valid": exists,
        "status": "valid" if exists else "invalid",
        "sample_type": sample_type,
    }