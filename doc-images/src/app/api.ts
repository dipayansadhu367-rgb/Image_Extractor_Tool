import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';


export interface ImageMeta {
  job_id: string;
  doc_id: number;   
  child_id: number;  
  page: number;
  index: number;
  width: number;
  height: number;
  filename: string;
  url: string;
  method: string;
}

export interface ProcessResponse {
  job_id: string;
  doc_id: number;     
  count: number;
  images: ImageMeta[];
}

export interface DocRow {
  doc_id: number;
  filename: string;
  page_count: number;
  created_at: string;
}
export interface ImageRow {
  doc_id: number;
  child_id: number;
  filename: string;
  page: number;
  method: string;
  url: string;
}

export interface SearchHit {
  doc_id: number;
  child_id: number;
  filename: string;
  url: string;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private base = 'http://127.0.0.1:8000';

  constructor(private http: HttpClient) {}

  process(
    file: File,
    mode: 'embedded' | 'scanned' | 'auto' = 'auto',
    minArea = 100000,
    format: 'png' | 'jpg' | 'jpeg' = 'jpg'
  ): Observable<ProcessResponse> {
    const form = new FormData();
    form.append('file', file);
    form.append('mode', mode);
    form.append('min_area', String(minArea));
    form.append('format', format);
    return this.http.post<ProcessResponse>(`${this.base}/process`, form);
  }

  rename(jobId: string, oldName: string, newName: string) {
    return this.http.post<{ ok: boolean; error?: string }>(
      `${this.base}/rename`,
      { job_id: jobId, old_name: oldName, new_name: newName }
    );
  }

  listDocs(): Observable<DocRow[]> {
    return this.http.get<DocRow[]>(`${this.base}/docs`);
  }

  listImages(docId: number): Observable<ImageRow[]> {
    return this.http.get<ImageRow[]>(`${this.base}/docs/${docId}/images`);
  }

  searchImages(q: string): Observable<SearchHit[]> {
    const params = new HttpParams().set('q', q);
    return this.http.get<SearchHit[]>(`${this.base}/search`, { params });
  }
}
