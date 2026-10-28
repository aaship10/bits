"""Keeps a copy of each raw uploaded CSV.

Uploads to the Catalyst Stratus bucket named by STRATUS_BUCKET when it is set and the
Catalyst SDK is available (i.e. on AppSail). Otherwise, or if Stratus fails, the file is
written to a local folder so an upload is never lost during development.
"""
import io
import os
import re

LOCAL_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "uploads"))


def _safe_name(forecast_id: str, filename: str) -> str:
    base = re.sub(r'[\s"<>#\\|]+', "_", os.path.basename(filename) or "upload.csv")  # chars Stratus rejects
    return f"{forecast_id}_{base}"


def _to_stratus(raw: bytes, key: str, req) -> str:
    import zcatalyst_sdk

    app = zcatalyst_sdk.initialize(req=req)
    bucket = app.stratus().bucket(os.environ["STRATUS_BUCKET"])
    bucket.put_object(key, io.BytesIO(raw), {"overwrite": "true"})
    return f"stratus://{os.environ['STRATUS_BUCKET']}/{key}"


def save_raw(raw: bytes, forecast_id: str, filename: str = "upload.csv", req=None) -> str:
    """Return where the file went. Raises only if both Stratus and local disk fail."""
    name = _safe_name(forecast_id, filename)
    if os.environ.get("STRATUS_BUCKET") and req is not None:
        try:
            return _to_stratus(raw, name, req)
        except Exception as e:  # noqa: BLE001  fall back to local disk
            print(f"WARNING: Stratus upload failed ({e}); saving locally", flush=True)
    os.makedirs(LOCAL_DIR, exist_ok=True)
    path = os.path.join(LOCAL_DIR, name)
    with open(path, "wb") as f:
        f.write(raw)
    return path
