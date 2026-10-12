import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type Params = Record<string, string | number | boolean | null | undefined>;

/** Thin wrapper over HttpClient. All URLs are relative to /api. */
@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  private params(p?: Params): HttpParams {
    let hp = new HttpParams();
    for (const [k, v] of Object.entries(p ?? {})) {
      if (v !== null && v !== undefined && v !== '') hp = hp.set(k, String(v));
    }
    return hp;
  }

  get<T = any>(url: string, params?: Params): Observable<T> {
    return this.http.get<T>(`/api/${url}`, { params: this.params(params) });
  }
  post<T = any>(url: string, body: any = {}): Observable<T> {
    return this.http.post<T>(`/api/${url}`, body);
  }
  patch<T = any>(url: string, body: any): Observable<T> {
    return this.http.patch<T>(`/api/${url}`, body);
  }
  put<T = any>(url: string, body: any): Observable<T> {
    return this.http.put<T>(`/api/${url}`, body);
  }
  delete<T = any>(url: string): Observable<T> {
    return this.http.delete<T>(`/api/${url}`);
  }

  /** Promise helpers for async/await style code in components. */
  getP<T = any>(url: string, params?: Params): Promise<T> {
    return firstValueFrom(this.get<T>(url, params));
  }
  postP<T = any>(url: string, body: any = {}): Promise<T> {
    return firstValueFrom(this.post<T>(url, body));
  }
  patchP<T = any>(url: string, body: any): Promise<T> {
    return firstValueFrom(this.patch<T>(url, body));
  }
  putP<T = any>(url: string, body: any): Promise<T> {
    return firstValueFrom(this.put<T>(url, body));
  }
  deleteP<T = any>(url: string): Promise<T> {
    return firstValueFrom(this.delete<T>(url));
  }

  /** Fetch every page of a paginated list (for pickers). */
  async all<T = any>(url: string, params?: Params): Promise<T[]> {
    const res: any = await this.getP(url, { ...params, page_size: 500 });
    return Array.isArray(res) ? res : res.results;
  }

  /** Download a protected file through the authenticated session. */
  async download(url: string, params?: Params, fallbackName = 'download'): Promise<void> {
    const resp = await firstValueFrom(
      this.http.get(`/api/${url}`, { params: this.params(params), responseType: 'blob', observe: 'response' }),
    );
    const cd = resp.headers.get('Content-Disposition') || '';
    const match = /filename="?([^"]+)"?/.exec(cd);
    const name = match ? match[1] : fallbackName;
    const blobUrl = URL.createObjectURL(resp.body as Blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
  }
}

/** Turn a DRF error response into a readable message + field errors. */
export function parseError(err: unknown): { message: string; fields: Record<string, string> } {
  const fields: Record<string, string> = {};
  if (!(err instanceof HttpErrorResponse)) return { message: 'Something went wrong.', fields };
  if (err.status === 0) return { message: 'Cannot reach the server. Check that the backend is running.', fields };
  if (err.status === 429) {
    const d = err.error?.detail;
    return { message: typeof d === 'string' ? d : 'Too many attempts. Please wait a moment and try again.', fields };
  }
  const body = err.error;
  if (body && typeof body === 'object' && !(body instanceof Blob)) {
    let message = '';
    for (const [k, v] of Object.entries(body)) {
      const text = Array.isArray(v) ? v.join(' ') : typeof v === 'object' ? JSON.stringify(v) : String(v);
      if (k === 'detail' || k === 'non_field_errors') message = text;
      else fields[k] = text;
    }
    if (!message && Object.keys(fields).length) {
      const [k, v] = Object.entries(fields)[0];
      message = Object.keys(fields).length === 1 ? `${labelize(k)}: ${v}` : 'Please correct the highlighted fields.';
    }
    return { message: message || `Request failed (${err.status}).`, fields };
  }
  if (err.status === 403) return { message: 'You do not have permission to do that.', fields };
  if (err.status === 404) return { message: 'Not found.', fields };
  return { message: `Request failed (${err.status}).`, fields };
}

export function labelize(key: string): string {
  return key.replace(/_ids?$/, '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}
