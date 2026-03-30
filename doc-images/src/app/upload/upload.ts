import { Component, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { ApiService, ImageMeta } from '../api';

@Component({
  selector: 'app-upload',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './upload.html',
  styleUrls: ['./upload.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UploadComponent {
  file: File | null = null;
  mode: 'embedded' | 'scanned' | 'auto' = 'auto';
  minArea = 10000;
  format: 'png' | 'jpg' | 'jpeg' = 'jpg';

  images$ = new BehaviorSubject<ImageMeta[]>([]);
  loading$ = new BehaviorSubject<boolean>(false);
  error$   = new BehaviorSubject<string>('');
  previewUrl: string | null = null;

  constructor(private api: ApiService, private cdr: ChangeDetectorRef) {}

  preview(url: string) {
    this.previewUrl = url;
    this.cdr.markForCheck();
  }

  onFile(e: Event) {
    const input = e.target as HTMLInputElement;
    this.file = input.files?.[0] ?? null;
  }

  process() {
    if (!this.file || this.loading$.value) return;
    this.loading$.next(true);
    this.error$.next('');
    this.api.process(this.file, this.mode, this.minArea, this.format).subscribe({
      next: (res) => {
        this.images$.next(res?.images ?? []);
        this.loading$.next(false);
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.loading$.next(false);
        this.error$.next(err?.message || 'Upload failed');
        this.cdr.markForCheck();
      }
    });
  }

  rename(img: ImageMeta, newName: string) {
    if (!newName || newName === img.filename) return;
    this.api.rename(img.job_id, img.filename, newName).subscribe({
      next: (r: any) => {
        if (r?.ok) {
          const curr = this.images$.value;
          const updated = curr.map(m =>
            m.filename === img.filename
              ? { ...m, filename: newName, url: m.url.replace(img.filename, newName) }
              : m
          );
          this.images$.next(updated);
        } else {
          this.error$.next(r?.error || 'Rename failed');
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.error$.next('Rename failed');
        this.cdr.markForCheck();
      },
    });
  }

  trackByName(_i: number, im: ImageMeta) { return im.filename; }
}