"""Extracts job rows from uploaded files — free and fully offline.

  CSV  -> header mapping (deterministic)
  PDF  -> embedded text if present, otherwise local OCR of the page images
  image-> local OCR

No API keys, no network calls, no per-use cost.
"""
import csv
import io
import os

from fields import FIELD_ORDER, csv_synonyms

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


class ExtractionError(Exception):
    pass


def ocr_available() -> bool:
    try:
        import ocr

        return ocr.available()
    except Exception:
        return False


# ---------------------------------------------------------------- PDF / image

def extract_document(data: bytes, ext: str, progress=None) -> list:
    import local_parse

    if ext == ".pdf":
        text = local_parse.pdf_text(data)
        if len(text.strip()) >= 120:          # real text layer — no OCR needed
            import portal_parse

            # Read it by position first. A generated PDF stores each column
            # separately, so flat text interleaves neighbouring columns; the
            # layout parser used for screenshots handles it properly.
            pages = local_parse.pdf_word_boxes(data)
            if pages:
                jobs = portal_parse.parse_pages(pages)
                if jobs:
                    return jobs
            jobs = local_parse.parse_jobs(text)
            if jobs:
                return jobs

        if not ocr_available():
            raise ExtractionError(
                "This PDF is made of page images (no selectable text), so it needs OCR. "
                "Install it once with:  py -m pip install --user rapidocr-onnxruntime pypdfium2"
            )
        import ocr
        import portal_parse

        pages = ocr.pdf_boxes(data, progress=progress)
        jobs = portal_parse.parse_pages(pages)
        if not jobs:
            flat = "\n".join(ocr.boxes_to_text(p) for p in pages)
            jobs = local_parse.parse_jobs(flat)
        if not jobs:
            raise ExtractionError(
                "No work-order details could be read from this PDF. If it is a photo of a "
                "page, try a sharper capture or a screenshot of the portal instead."
            )
        return jobs

    # single image
    if not ocr_available():
        raise ExtractionError(
            "Reading screenshots needs OCR. Install it once with:  "
            "py -m pip install --user rapidocr-onnxruntime pypdfium2"
        )
    import ocr
    import portal_parse

    boxes = ocr.image_boxes(data)
    jobs = portal_parse.parse_pages([boxes])
    if not jobs:
        jobs = local_parse.parse_jobs(ocr.boxes_to_text(boxes))
    if not jobs:
        raise ExtractionError("No work-order details could be read from this image.")
    return jobs


# ---------------------------------------------------------------- CSV

def _csv_header_map(headers: list) -> dict:
    mapping, used = {}, set()
    normed = [h.strip().lower() for h in headers]
    for field in FIELD_ORDER:
        for syn in csv_synonyms(field):
            for i, h in enumerate(normed):
                if i in mapping or not h:
                    continue
                if h == syn and field not in used:
                    mapping[i] = field
                    used.add(field)
                    break
            if field in used:
                break
    return mapping


def extract_csv(data: bytes) -> list:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise ExtractionError("The CSV file is empty.")

    mapping = _csv_header_map(rows[0])
    if len(mapping) < 3:
        raise ExtractionError(
            "Could not recognize this CSV's column headers. Rename them to match the "
            "sheet (Job ID, SOW, NTE, Address, Deadline…) and try again."
        )

    out = []
    for r in rows[1:]:
        job = {f: "" for f in FIELD_ORDER}
        for i, field in mapping.items():
            if i < len(r) and r[i].strip():
                job[field] = r[i].strip()
        if any(job.values()):
            out.append(job)
    return out


# ---------------------------------------------------------------- entry point

def extract_file(filename: str, data: bytes, progress=None) -> list:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        return extract_csv(data)
    if ext == ".pdf" or ext in IMAGE_EXTS:
        return extract_document(data, ext, progress=progress)
    raise ExtractionError(f"Unsupported file type: {ext or filename}")
