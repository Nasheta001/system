"""Upload validation: size limits, extension allow-lists and content sniffing."""
import os
import re
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc"}

MAGIC = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".webp": [b"RIFF"],
    ".docx": [b"PK\x03\x04"],
    ".doc": [b"\xd0\xcf\x11\xe0"],
}


def _check_size(f):
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    if f.size > limit:
        raise ValidationError(f"File is too large (maximum {settings.MAX_UPLOAD_MB} MB).")


def _check_magic(f, ext):
    signatures = MAGIC.get(ext)
    if not signatures:
        return
    pos = f.tell() if hasattr(f, "tell") else 0
    f.seek(0)
    head = f.read(8)
    f.seek(pos)
    if not any(head.startswith(sig) for sig in signatures):
        raise ValidationError("File content does not match its extension.")


def validate_image_upload(f):
    _check_size(f)
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError("Only JPG, PNG or WEBP images are allowed.")
    _check_magic(f, ext)
    try:
        from PIL import Image

        pos = f.tell()
        f.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(f)
            if img.width * img.height > 40_000_000:
                raise ValidationError("Image dimensions are too large.")
            img.verify()
        f.seek(pos)
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("The uploaded file is not a valid image.") from exc


def validate_document_upload(f):
    _check_size(f)
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in DOCUMENT_EXTENSIONS:
        raise ValidationError("Allowed file types: PDF, DOCX, DOC, JPG, PNG.")
    _check_magic(f, ext)


PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{7,18}$")


def validate_phone(value):
    if value and not PHONE_RE.match(value.strip()):
        raise ValidationError("Enter a valid phone number, e.g. 0712 345 678 or +254712345678.")


def sanitize_image(f):
    """Re-encode an uploaded image: drops EXIF/GPS metadata and anything
    appended to the file (polyglots). Returns a new in-memory upload."""
    from io import BytesIO

    from django.core.files.uploadedfile import InMemoryUploadedFile
    from PIL import Image, ImageOps

    f.seek(0)
    img = ImageOps.exif_transpose(Image.open(f))
    ext = os.path.splitext(f.name)[1].lower()
    fmt = {".png": "PNG", ".webp": "WEBP"}.get(ext, "JPEG")
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = BytesIO()
    if fmt == "PNG":
        img.save(buf, fmt, optimize=True)
    else:
        img.save(buf, fmt, quality=85)
    size = buf.tell()
    buf.seek(0)
    content_type = {"PNG": "image/png", "WEBP": "image/webp"}.get(fmt, "image/jpeg")
    return InMemoryUploadedFile(buf, "image", f.name, content_type, size, None)
