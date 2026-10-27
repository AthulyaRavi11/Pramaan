"""Document reading, OCR, classification and field extraction."""
from __future__ import annotations

import io
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime

import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from ..core import config

# Windows: Tesseract is usually not on PATH. Honour TESSERACT_CMD, else try the default install folder.
_tess = os.environ.get("TESSERACT_CMD")
if not _tess and os.name == "nt":
    for _p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(_p):
            _tess = _p
            break
if _tess:
    pytesseract.pytesseract.tesseract_cmd = _tess

# pdfium is not thread-safe: concurrent renders from the API thread pool crash the process.
PDFIUM_LOCK = threading.RLock()


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Enhance image resolution, sharpness, and contrast before passing to OCR."""
    # Convert transparent backgrounds to crisp white
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alpha = img.convert("RGBA")
        bg = Image.new("RGBA", alpha.size, (255, 255, 255))
        bg.paste(alpha, mask=alpha.split()[3])
        img = bg.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Upscale low-res images / screenshots (min 2200px on long edge) for OCR character clarity
    w, h = img.size
    target_dim = 2200
    if max(w, h) < target_dim:
        scale = target_dim / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    # Grayscale & contrast enhancement
    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(1.35)
    return enhanced


def render_pages(path: str, scale: float, max_pages: int = 3, only: int | None = None) -> list[Image.Image]:
    """Render PDF pages to PIL images, one call at a time."""
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(path)
        try:
            idx = [min(only, len(pdf)) - 1] if only else range(min(len(pdf), max_pages))
            return [pdf[i].render(scale=scale).to_pil() for i in idx]
        finally:
            pdf.close()


MIN_TEXT_CHARS = 25          # below this a PDF page is treated as scanned -> OCR
OCR_DPI = 300


@dataclass
class ReadResult:
    text: str
    pages: list[str]
    ocr_used: bool
    ocr_confidence: float | None
    images: list[Image.Image] = field(default_factory=list)   # rendered first pages / the image itself
    chars: list[dict] = field(default_factory=list)            # pdf chars with font info (text layer only)
    pdf_metadata: dict = field(default_factory=dict)
    page_count: int = 0


def ocr_postcorrect(text: str) -> str:
    """Fix OCR confusions inside identifier-like tokens only (e.g. 'KA’NOT/01234' -> 'KA/NOT/01234')."""
    # Replace quotes/slits with '/' only when adjacent to uppercase letters, NOT between digits (to preserve numbers like 18,500)
    text = re.sub(r"(?<=[A-Z])[’‘'|,]+(?=[A-Z0-9])|(?<=[A-Z0-9])[’‘'|,]+(?=[A-Z])", "/", text)
    text = re.sub(r"\b(20\d\d)\.(\d\d)\b", r"\1-\2", text)
    text = re.sub(r"['`.]+(\d{6,12})", r"1-\1", text)
    return text


def _ocr(img: Image.Image) -> tuple[str, float]:
    proc = preprocess_for_ocr(img)
    try:
        data = pytesseract.image_to_data(proc, output_type=pytesseract.Output.DICT, config="--psm 6")
        confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
        text = ocr_postcorrect(pytesseract.image_to_string(proc, config="--psm 6"))
        if text.strip():
            return text, (sum(confs) / len(confs) / 100) if confs else 0.0
    except Exception:
        pass

    # Windows native OCR fallback via winocr
    try:
        import asyncio, winocr, concurrent.futures

        def _run_winocr_sync():
            def _worker():
                async def _coro():
                    return await winocr.recognize_pil(proc, "en")
                return asyncio.run(_coro())

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(_worker).result()
            else:
                return _worker()

        res = _run_winocr_sync()
        if hasattr(res, "lines") and res.lines:
            raw_text = "\n".join(ln.text for ln in res.lines if hasattr(ln, "text"))
        else:
            raw_text = res.text or ""
        text = ocr_postcorrect(raw_text)
        if text.strip():
            return text, 0.88
    except Exception:
        pass

    return "", 0.0


def read_document(path: str, mime: str, ocr: bool = True) -> ReadResult:
    if mime == "application/pdf":
        pages, chars, ocr_used, confs = [], [], False, []
        with pdfplumber.open(path) as pdf:
            meta = dict(pdf.metadata or {})
            n = len(pdf.pages)
            for i, p in enumerate(pdf.pages):
                t = p.extract_text() or ""
                for ch in p.chars:
                    chars.append({"page": i + 1, "text": ch["text"], "font": ch.get("fontname", ""),
                                  "size": round(ch.get("size", 0), 1), "x0": ch["x0"], "top": ch["top"],
                                  "x1": ch["x1"], "bottom": ch["bottom"]})
                pages.append(t)
        rendered = render_pages(path, OCR_DPI / 72)
        for i, img in enumerate(rendered):
            if ocr and len(pages[i].strip()) < MIN_TEXT_CHARS:
                t, cf = _ocr(img)
                pages[i] = t
                ocr_used = True
                confs.append(cf)
        return ReadResult("\n".join(pages), pages, ocr_used, (sum(confs) / len(confs)) if confs else None,
                          rendered, chars, meta, n)

    img = Image.open(path)
    img.load()
    if ocr:
        t, cf = _ocr(img)
        return ReadResult(t, [t], True, cf, [img], [], {}, 1)
    return ReadResult("", [""], False, None, [img], [], {}, 1)


# ---------------------------------------------------------------- classification

def classify(text: str) -> tuple[str | None, float, dict]:
    """Keyword scoring over the configured document types. Returns (type, confidence, scores)."""
    low = text.lower()
    scores = {}
    for dtype, spec in config.documents().items():
        kws = spec.get("keywords") or []
        if not kws:
            continue
        hits = sum(1 for k in kws if k in low)
        # field-label hits are strong evidence for the type
        label_hits = sum(1 for pat in (spec.get("fields") or {}).values() if re.search(pat, text, re.I | re.M))
        scores[dtype] = hits + 1.5 * label_hits
    if not scores or max(scores.values()) == 0:
        return None, 0.0, scores
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    return best, round(scores[best] / total, 2), scores


# ---------------------------------------------------------------- extraction

DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y")


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip(" .;,|")


def extract_fields(text: str, doc_type: str, base_conf: float = 0.99) -> dict:
    spec = config.documents().get(doc_type, {})
    out = {}
    lines = text.splitlines()
    for name, pat in (spec.get("fields") or {}).items():
        rx = re.compile(pat, re.I)
        matched = False
        # 1. Single line check
        for ln_no, line in enumerate(lines, 1):
            m = rx.search(line)
            if m:
                raw = _clean(m.group(1))
                norm: object = raw
                if name in (spec.get("date_fields") or []):
                    d = parse_date(raw)
                    norm = d.isoformat() if d else None
                elif name.endswith("_sqm"):
                    try:
                        clean_num = re.sub(r"[^\d.]", "", raw.replace("/", ""))
                        norm = float(clean_num)
                    except ValueError:
                        norm = None
                out[name] = {"value": raw, "normalized": norm, "line": ln_no, "line_text": line.strip(),
                             "confidence": base_conf if norm is not None else round(base_conf * 0.5, 2)}
                matched = True
                break
        if matched:
            continue
        # 2. Sliding 2-line window (handles wrapped labels/values across lines)
        for ln_no in range(len(lines) - 1):
            combined = lines[ln_no].strip() + " " + lines[ln_no + 1].strip()
            m = rx.search(combined)
            if m:
                raw = _clean(m.group(1))
                norm: object = raw
                if name in (spec.get("date_fields") or []):
                    d = parse_date(raw)
                    norm = d.isoformat() if d else None
                elif name.endswith("_sqm"):
                    try:
                        clean_num = re.sub(r"[^\d.]", "", raw.replace("/", ""))
                        norm = float(clean_num)
                    except ValueError:
                        norm = None
                out[name] = {"value": raw, "normalized": norm, "line": ln_no + 1, "line_text": combined,
                             "confidence": round(base_conf * 0.9, 2)}
                break
    return out


def normalize_name(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(the|of|and|&)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()
