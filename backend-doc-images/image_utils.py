from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import io
import re
import unicodedata
import fitz 
from PIL import Image
try:
    import numpy as np
    import cv2
except Exception:
    np = None
    cv2 = None

try:
    import pytesseract
except Exception:
    pytesseract = None 

def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len] or "image"

def _ensure_unique(base: str, existing: set[str]) -> str:
    name = base
    i = 2
    while name in existing:
        name = f"{base}-{i}"
        i += 1
    existing.add(name)
    return name

def _normalize_fmt(fmt: str | None) -> str:
    f = (fmt or "png").strip().lower()
    if f == "jpg":
        f = "jpeg"
    return "jpeg" if f == "jpeg" else "png"

def _save_bytes(img_bytes: bytes, out_dir: Path, base_name: str, fmt: str = "png") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = _normalize_fmt(fmt)
    path = out_dir / f"{base_name}.{fmt}"
    img = Image.open(io.BytesIO(img_bytes))
    if fmt == "jpeg":
        img = img.convert("RGB")
        img.save(path, format="JPEG", quality=95, optimize=True)
    else:
        img.save(path, format="PNG")
    return path

CAPTION_PATS = [
    re.compile(r"^\s*(image|img)\s*([0-9]+)\b[:.)-]?\s*(.*)$", re.I),
    re.compile(r"^\s*(fig(?:\.|ure)?)\s*([0-9]+)\b[:.)-]?\s*(.*)$", re.I),
    re.compile(r"^\s*(photo)\s*([0-9]+)\b[:.)-]?\s*(.*)$", re.I),
    re.compile(r"^\s*(plate)\s*([0-9]+)\b[:.)-]?\s*(.*)$", re.I),
]

def _canonical_caption_from_text(text: str) -> Optional[str]:
    for pat in CAPTION_PATS:
        m = pat.match(text)
        if m:
            label = f"{m.group(1).capitalize()} {m.group(2)}"
            rest = (m.group(3) or "").strip()
            cap = label if not rest else f"{label} {rest}"
            return re.sub(r"[:.\-–—]\s*$", "", cap).strip()
    return None

def _caption_candidates_from_words(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    try:
        words = page.get_text("words") or []
    except Exception:
        return []

    from collections import defaultdict
    groups = defaultdict(list)
    for w in words:
        if len(w) < 8:
            continue
        x0, y0, x1, y1, txt, bno, lno, _ = w
        groups[(bno, lno)].append((x0, y0, x1, y1, txt))

    candidates: list[tuple[fitz.Rect, str]] = []
    for (_bno, _lno), spans in groups.items():
        spans.sort(key=lambda s: s[0])  # left to right
        text = " ".join(s[4] for s in spans).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        cap = _canonical_caption_from_text(text)
        if not cap:
            continue
        x0 = min(s[0] for s in spans); y0 = min(s[1] for s in spans)
        x1 = max(s[2] for s in spans); y1 = max(s[3] for s in spans)
        candidates.append((fitz.Rect(x0, y0, x1, y1), cap))
    return candidates

def _pick_nearest_caption(img_rect: fitz.Rect, caps: list[tuple[fitz.Rect, str]]) -> Optional[str]:
    if not caps or img_rect is None:
        return None
    center_x = (img_rect.x0 + img_rect.x1) / 2
    best_cap: Optional[str] = None
    best_score = 1e18
    for lb, cap in caps:
        vdist = (lb.y0 - img_rect.y1) if lb.y0 >= img_rect.y1 else (img_rect.y0 - lb.y1 + 12)
        horiz = abs(((lb.x0 + lb.x1) / 2) - center_x) * 0.01
        score = vdist + horiz
        if score < best_score:
            best_score = score
            best_cap = cap
    return best_cap

def _detect_caption_inside_image(img_bytes: bytes) -> Optional[str]:
    if pytesseract is None:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes))

        g = img.convert("L")

        g = g.point(lambda x: 255 if x > 200 else (0 if x < 30 else x))

        data = pytesseract.image_to_data(g, lang="eng", config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT)

        lines = {}
        n = len(data["text"])
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            conf = float(data["conf"][i]) if str(data["conf"][i]).strip().isdigit() else -1.0
            line_no = data["line_num"][i]
            if txt and conf >= 60:
                lines.setdefault(line_no, []).append((txt, conf))

        full_text = " ".join(t for i in range(n) for t in [(data["text"][i] or "").strip()] if t)
        full_text = re.sub(r"\s+", " ", full_text)
        cap = _canonical_caption_from_text(full_text)
        if cap:
            return cap
        best_line = None
        best_score = -1.0
        for line_no, items in lines.items():
            text_line = " ".join(t for t, _ in items)
            clean = re.sub(r"[^A-Za-z0-9\s\-:/]", "", text_line).strip()
            if len(clean) < 8 or len(clean.split()) < 3:
                continue
            alpha_ratio = sum(c.isalpha() for c in clean) / max(1, len(clean))
            conf_avg = sum(c for _, c in items) / len(items)
            score = len(clean) * 0.6 + alpha_ratio * 40 + conf_avg * 0.4
            if score > best_score:
                best_score = score
                best_line = clean

        if best_line:

            best_line = re.sub(r"\s+", " ", best_line)
            return best_line[:80]

    except Exception:
        pass
    return None


def extract_images_embedded(
    pdf_path: Path,
    out_root: Path,
    base_url: str,
    job_id: str,
    fmt: str = "png"
) -> List[Dict]:

    FULLPAGE_AREA_RATIO = 0.60
    EDGE_TOLERANCE_PT   = 18.0 

    fmt = _normalize_fmt(fmt)
    out_dir = out_root / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    metas: List[Dict] = []
    existing_names: set[str] = set()

    doc = fitz.open(pdf_path)
    for page_num in range(len(doc)):
        page = doc[page_num]
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        images = page.get_images(full=True)

        caption_lines = _caption_candidates_from_words(page)

        for idx, img in enumerate(images, start=1):
            xref = img[0]

            rect: Optional[fitz.Rect] = None
            try:
                rects = page.get_image_rects(xref) or []
                if rects:
                    rect = rects[0]
            except Exception:
                rects = []

            is_fullpage_like = False
            if rect is not None:
                area_ratio = (rect.width * rect.height) / max(1.0, page_area)
                hugs_left   = abs(rect.x0 - page_rect.x0) <= EDGE_TOLERANCE_PT
                hugs_right  = abs(rect.x1 - page_rect.x1) <= EDGE_TOLERANCE_PT
                hugs_top    = abs(rect.y0 - page_rect.y0) <= EDGE_TOLERANCE_PT
                hugs_bottom = abs(rect.y1 - page_rect.y1) <= EDGE_TOLERANCE_PT
                hugs_edges  = sum([hugs_left, hugs_right, hugs_top, hugs_bottom]) >= 3
                if area_ratio >= FULLPAGE_AREA_RATIO or hugs_edges:
                    is_fullpage_like = True
            if is_fullpage_like:
                continue
            pix = fitz.Pixmap(doc, xref)
            img_bytes = pix.tobytes("png")

            caption = _pick_nearest_caption(rect, caption_lines)

            if not caption:
                caption = _detect_caption_inside_image(img_bytes)

            base = _slugify(caption) if caption else f"p{page_num+1:03d}_img{idx:03d}"
            base = _ensure_unique(base, existing_names)

            out_path = _save_bytes(img_bytes, out_dir, base, fmt)
            metas.append({
                "job_id": job_id,
                "page": page_num + 1,
                "index": idx,
                "width": pix.width,
                "height": pix.height,
                "filename": out_path.name,
                "url": f"{base_url}/data/images/{job_id}/{out_path.name}",
                "method": "embedded" + ("+caption" if caption else ""),
            })

    doc.close()
    return metas


def detect_images_scanned(
    pdf_path: Path,
    out_root: Path,
    base_url: str,
    job_id: str,
    min_area: int = 10_000,
    fmt: str = "png"
) -> List[Dict]:

    out_dir = out_root / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    metas: List[Dict] = []
    fmt = _normalize_fmt(fmt)

    doc = fitz.open(pdf_path)
    for p in range(len(doc)):
        page = doc[p]
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        page_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        if cv2 is None or np is None:

            name = f"p{p+1:03d}_page"
            out_path = out_dir / f"{name}.{fmt}"
            if fmt == "jpeg":
                page_img.convert("RGB").save(out_path, format="JPEG", quality=95, optimize=True)
            else:
                page_img.save(out_path, format="PNG")
            metas.append({
                "job_id": job_id, "page": p + 1, "index": 1,
                "width": pix.width, "height": pix.height,
                "filename": out_path.name,
                "url": f"{base_url}/data/images/{job_id}/{out_path.name}",
                "method": "scanned",
            })
            continue

        arr = np.array(page_img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((5, 5), np.uint8)
        dil = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        idx = 1
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w * h < min_area:
                continue
            crop = arr[y:y+h, x:x+w]
            crop_img = Image.fromarray(crop)
            ocr_caption = None
            if pytesseract is not None:
                try:
                    buf = io.BytesIO()
                    crop_img.save(buf, format="PNG")
                    ocr_caption = _detect_caption_inside_image(buf.getvalue())
                except Exception:
                    ocr_caption = None

            name_base = _slugify(ocr_caption) if ocr_caption else f"p{p+1:03d}_det{idx:03d}"
            out_path = out_dir / f"{name_base}.{fmt}"
            if fmt == "jpeg":
                crop_img.convert("RGB").save(out_path, format="JPEG", quality=95, optimize=True)
            else:
                crop_img.save(out_path, format="PNG")

            metas.append({
                "job_id": job_id, "page": p + 1, "index": idx,
                "width": int(w), "height": int(h),
                "filename": out_path.name,
                "url": f"{base_url}/data/images/{job_id}/{out_path.name}",
                "method": "scanned" + ("+ocr" if ocr_caption else ""),
            })
            idx += 1

    doc.close()
    return metas
