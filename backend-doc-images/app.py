import os, uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sqlalchemy.orm import Session
from image_utils import extract_images_embedded, detect_images_scanned
from db import init_db, get_db, Document, Image

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
STORAGE = Path(os.getenv("STORAGE_DIR", "./data")).resolve()
UPLOADS = STORAGE / "uploads"
IMAGES = STORAGE / "images"

for d in (UPLOADS, IMAGES):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Doc→Images")

init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.mount("/data", StaticFiles(directory=str(STORAGE)), name="data")


class ImageMeta(BaseModel):
    job_id: str
    doc_id: int        
    child_id: int       
    page: int
    index: int
    width: int
    height: int
    filename: str
    url: str
    method: str

class ProcessResponse(BaseModel):
    job_id: str
    doc_id: int           
    count: int
    images: List[ImageMeta]



@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process", response_model=ProcessResponse)
async def process_pdf(
    file: UploadFile = File(...),
    mode: str = Form("auto"),
    min_area: int = Form(200_000),
    format: str = Form("jpg"),
    db: Session = Depends(get_db),
):
    job_id = uuid.uuid4().hex[:12]
    upath = UPLOADS / f"{job_id}_{file.filename}"
    upath.write_bytes(await file.read())
    fmt = (format or "png").strip().lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in ("png", "jpeg"):
        fmt = "png"

    import fitz
    with fitz.open(upath) as d:
        page_count = len(d)

    doc_row = Document(job_id=job_id, filename=file.filename, page_count=page_count)
    db.add(doc_row)
    db.commit()
    db.refresh(doc_row)  

    if mode == "embedded":
        extracted = extract_images_embedded(upath, IMAGES, BASE_URL, job_id, fmt=fmt)
    elif mode == "scanned":
        extracted = detect_images_scanned(upath, IMAGES, BASE_URL, job_id, min_area=min_area, fmt=fmt)
    else: 
        extracted = extract_images_embedded(upath, IMAGES, BASE_URL, job_id, fmt=fmt)
        if not extracted and page_count <= 20:
            extracted = detect_images_scanned(upath, IMAGES, BASE_URL, job_id, min_area=min_area, fmt=fmt)

    images_meta: List[ImageMeta] = []
    for child_id, m in enumerate(extracted, start=1):
        db.add(Image(
            doc_id=doc_row.id,
            child_id=child_id,
            page=m["page"],
            index_in_pdf=m["index"],
            width=m["width"],
            height=m["height"],
            method=m["method"],
            filename=m["filename"],
            url=m["url"],
        ))
        images_meta.append(ImageMeta(
            job_id=job_id,
            doc_id=doc_row.id,
            child_id=child_id,
            page=m["page"],
            index=m["index"],
            width=m["width"],
            height=m["height"],
            filename=m["filename"],
            url=m["url"],
            method=m["method"],
        ))

    db.commit()

    return {"job_id": job_id, "doc_id": doc_row.id, "count": len(images_meta), "images": images_meta}


class RenameReq(BaseModel):
    job_id: str
    old_name: str
    new_name: str


@app.post("/rename")
def rename(req: RenameReq):
    src = IMAGES / req.job_id / req.old_name
    dst = IMAGES / req.job_id / req.new_name
    if not src.exists():
        return {"ok": False, "error": "File not found"}
    if dst.exists():
        return {"ok": False, "error": "Target exists"}
    src.rename(dst)
    return {"ok": True}


@app.get("/docs")
def list_docs(db: Session = Depends(get_db)):
    rows = db.query(Document).order_by(Document.id.desc()).all()
    return [
        {"doc_id": r.id, "filename": r.filename, "page_count": r.page_count, "created_at": r.created_at}
        for r in rows
    ]


@app.get("/docs/{doc_id}/images")
def list_images(doc_id: int, db: Session = Depends(get_db)):
    rows = db.query(Image).filter(Image.doc_id == doc_id).order_by(Image.child_id).all()
    return [
        {"doc_id": r.doc_id, "child_id": r.child_id, "filename": r.filename, "page": r.page,
         "method": r.method, "url": r.url}
        for r in rows
    ]


@app.get("/search")
def search_images(q: str, db: Session = Depends(get_db)):
    ql = f"%{q.lower()}%"
    rows = db.execute(
        """
        SELECT d.id AS doc_id, i.child_id, i.filename, i.url
        FROM images i
        JOIN documents d ON d.id = i.doc_id
        WHERE lower(i.filename) LIKE :q
        ORDER BY d.id, i.child_id
        """,
        {"q": ql},
    ).all()
    return [dict(r._mapping) for r in rows]


@app.get("/")
def root():
    return {"ok": True, "message": "Doc→Images backend ready. Try /health or /docs"}
