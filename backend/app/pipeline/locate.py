"""Find where a value is printed on a document, so the dashboard can highlight it.

Digital PDFs use the text layer; scans and images use Tesseract word boxes.
Boxes are returned normalised to 0..1 of the page so the UI can draw them at any size.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

import pdfplumber
import pytesseract
from PIL import Image

from . import extract  # noqa: F401  (configures the Tesseract path on Windows)

OCR_SCALE = 200 / 72


def _norm(s: str) -> str:
    return re.sub(r"[^\w/\-.,]", "", s.lower()).strip(".,:;")


def _ocr_words(img: Image.Image, page: int) -> list[dict]:
    w, h = img.size
    d = pytesseract.image_to_data(img.convert("L"), output_type=pytesseract.Output.DICT, config="--psm 6")
    out = []
    for i, t in enumerate(d["text"]):
        if t.strip() and float(d["conf"][i]) >= 0:
            x, y, bw, bh = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            out.append({"page": page, "text": t, "box": [x / w, y / h, (x + bw) / w, (y + bh) / h]})
    return out


@lru_cache(maxsize=256)
def words(path: str, mime: str) -> tuple:
    out: list[dict] = []
    if mime == "application/pdf":
        with pdfplumber.open(path) as pdf:
            for i, p in enumerate(pdf.pages[:3]):
                ws = p.extract_words()
                if sum(len(w["text"]) for w in ws) >= 25:
                    out += [{"page": i + 1, "text": w["text"],
                             "box": [w["x0"] / p.width, w["top"] / p.height, w["x1"] / p.width, w["bottom"] / p.height]}
                            for w in ws]
                    continue
                out += _ocr_words(extract.render_pages(path, OCR_SCALE, only=i + 1)[0], i + 1)
    else:
        out = _ocr_words(Image.open(path), 1)
    return tuple(out)


def _match(token: str, word: str) -> bool:
    a, b = _norm(token), _norm(word)
    if not a or not b:
        return False
    if a == b or (len(a) >= 4 and a in b):
        return True
    return len(a) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.8


def find(path: str, mime: str, value: str) -> list[dict]:
    """Return [{page, box}] for the best occurrence of value (one box per printed line)."""
    tokens = [t for t in str(value).split() if _norm(t)]
    if not tokens:
        return []
    ws = list(words(path, mime))
    for i in range(len(ws)):
        if not _match(tokens[0], ws[i]["text"]):
            continue
        seq = [ws[i]]
        j = i + 1
        for t in tokens[1:]:
            if j < len(ws) and _match(t, ws[j]["text"]):
                seq.append(ws[j])
                j += 1
            else:
                break
        if len(seq) < max(1, int(len(tokens) * 0.75)):
            continue
        lines: dict = {}
        for w in seq:
            key = (w["page"], round(w["box"][1] * 80))
            b = lines.setdefault(key, list(w["box"]))
            b[0], b[1] = min(b[0], w["box"][0]), min(b[1], w["box"][1])
            b[2], b[3] = max(b[2], w["box"][2]), max(b[3], w["box"][3])
        return [{"page": k[0], "box": [round(x, 4) for x in b]} for k, b in lines.items()]
    return []
