import { signal } from '@angular/core';
import { Api, parseError } from '../core/api.service';

/** Paginated, filterable list backed by a DRF endpoint. */
export class ListState<T = any> {
  readonly items = signal<T[]>([]);
  readonly count = signal(0);
  readonly loading = signal(false);
  readonly loaded = signal(false);
  readonly error = signal('');
  readonly page = signal(1);
  filters: Record<string, any>;
  private seq = 0;

  constructor(private api: Api, private url: string, defaults: Record<string, any> = {}, public pageSize = 25) {
    this.filters = { ...defaults };
  }

  async load(resetPage = false) {
    if (resetPage) this.page.set(1);
    const mine = ++this.seq;
    this.loading.set(true);
    this.error.set('');
    try {
      const r: any = await this.api.getP(this.url, { ...this.filters, page: this.page(), page_size: this.pageSize });
      if (mine !== this.seq) return;
      const rows = Array.isArray(r) ? r : r.results;
      this.items.set(rows);
      this.count.set(Array.isArray(r) ? rows.length : r.count);
    } catch (e) {
      if (mine === this.seq) this.error.set(parseError(e).message);
    } finally {
      if (mine === this.seq) {
        this.loading.set(false);
        this.loaded.set(true);
      }
    }
  }

  go(page: number) {
    this.page.set(page);
    this.load();
  }

  private timer: any;
  /** Debounced reload for search boxes. */
  search() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(true), 300);
  }
}

/** Builds a FormData object, skipping null/undefined values. */
export function toFormData(values: Record<string, any>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) v.forEach((x) => fd.append(k, String(x)));
    else if (v instanceof Blob) fd.append(k, v);
    else fd.append(k, String(v));
  }
  return fd;
}
