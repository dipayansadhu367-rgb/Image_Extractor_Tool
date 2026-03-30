
Service	Port	URL	Notes
Angular App	4200	http://localhost:4200	UI for uploads
FastAPI API	8000	http://127.0.0.1:8000	Backend (PDF→images)

cd ~/Projects/backend-doc-images
source .venv/bin/activate
python -m uvicorn app:app --reload --port 8000 (OR) python3 -m uvicorn app:app --reload --port 8000

cd ~/Projects/doc-images
ng serve
