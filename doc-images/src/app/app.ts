import { Component } from '@angular/core';
import { UploadComponent } from './upload/upload';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [UploadComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {}
