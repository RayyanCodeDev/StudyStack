import base64
import io
from PIL import Image, ImageOps
from backend.auth import db

MAX_PDF_STORE_MB = 3  # larger PDFs keep only their name and page range


def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


def make_image_source(uploaded_file):
    """Shrink a screenshot to a small JPEG so it can be stored with the set."""
    try:
        img = Image.open(io.BytesIO(uploaded_file.getvalue()))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        return {"kind": "image", "name": uploaded_file.name, "page_range": None, "data": _b64(buf.getvalue())}
    except Exception:
        return None


def make_pdf_source(name, start, end, pdf_bytes):
    data = _b64(pdf_bytes) if len(pdf_bytes) <= MAX_PDF_STORE_MB * 1024 * 1024 else None
    return {"kind": "pdf", "name": name, "page_range": f"{start}-{end}", "data": data}


def source_bytes(src):
    """Decode the stored file, or None if there isn't one."""
    try:
        return base64.b64decode(src["data"]) if src and src.get("data") else None
    except Exception:
        return None


def save_source(set_id, src):
    """Returns an error message, or None on success. Never raises."""
    try:
        db().table("study_sources").insert({
            "set_id": set_id,
            "kind": src["kind"],
            "name": (src.get("name") or "")[:200],
            "page_range": src.get("page_range"),
            "data": src.get("data"),
        }).execute()
        return None
    except Exception:
        return "Couldn't store the original file."


def load_source(set_id):
    """Returns the stored upload for a set, or None."""
    try:
        r = (db().table("study_sources").select("kind,name,page_range,data")
             .eq("set_id", set_id).limit(1).execute())
        return r.data[0] if r.data else None
    except Exception:
        return None
