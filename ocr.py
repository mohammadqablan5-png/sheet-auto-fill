"""Offline OCR for image-based PDFs and screenshots.

Free and fully local: pypdfium2 renders pages to bitmaps and
rapidocr-onnxruntime reads the text. No API calls, no network, no cost.

Returns positioned text boxes so the parser can use the page layout
(label above value) rather than guessing from a flattened text dump.
"""
import io

DEFAULT_DPI = 300          # tested sweet spot for portal screenshots
_engine = None


def available() -> bool:
    try:
        import numpy  # noqa: F401
        import pypdfium2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:
        return False


def _get_engine():
    """Loads the OCR models once (a few seconds on first use)."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def _to_boxes(result) -> list:
    boxes = []
    for entry in result or []:
        box, text = entry[0], str(entry[1] or "").strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append({
            "text": text,
            "x0": min(xs), "x1": max(xs),
            "y0": min(ys), "y1": max(ys),
            "h": max(ys) - min(ys),
        })
    boxes.sort(key=lambda b: (b["y0"], b["x0"]))
    return boxes


def image_boxes(data: bytes) -> list:
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    result, _ = _get_engine()(np.array(img))
    return _to_boxes(result)


def pdf_boxes(data: bytes, dpi: int = DEFAULT_DPI, max_pages: int = 20,
              progress=None) -> list:
    """-> list of pages, each a list of text boxes."""
    import numpy as np
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(io.BytesIO(data))
    engine = _get_engine()
    pages = []
    n = min(len(doc), max_pages)
    for i in range(n):
        if progress:
            progress(i + 1, n)
        img = doc[i].render(scale=dpi / 72.0).to_pil().convert("RGB")
        result, _ = engine(np.array(img))
        pages.append(_to_boxes(result))
    return pages


def boxes_to_text(boxes: list) -> str:
    """Flatten boxes into reading-order lines (fallback for generic parsing)."""
    if not boxes:
        return ""
    heights = sorted(b["h"] for b in boxes)
    tol = max(6.0, heights[len(heights) // 2] * 0.6)
    lines, current, base = [], [], None
    for b in sorted(boxes, key=lambda b: (b["y0"], b["x0"])):
        cy = (b["y0"] + b["y1"]) / 2
        if base is None or abs(cy - base) <= tol:
            current.append(b)
            base = cy if base is None else base
        else:
            lines.append(current)
            current, base = [b], cy
    if current:
        lines.append(current)
    return "\n".join(
        "   ".join(x["text"] for x in sorted(line, key=lambda b: b["x0"]))
        for line in lines)
