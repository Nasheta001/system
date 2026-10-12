import { Injectable, inject, signal } from '@angular/core';
import { Api } from './api.service';

export interface Company {
  name: string;
  tagline: string;
  about: string;
  phone: string;
  whatsapp: string;
  email: string;
  address: string;
  currency: string;
  faq: { question: string; answer: string }[];
  privacy_notice: string;
  turnstile_site_key: string | null;
}

/** Public company profile, loaded once and shared. */
@Injectable({ providedIn: 'root' })
export class CompanyStore {
  private api = inject(Api);
  readonly company = signal<Company | null>(null);
  private loading: Promise<void> | null = null;

  load(): Promise<void> {
    if (!this.loading) {
      this.loading = this.api
        .getP<Company>('public/company/')
        .then((c) => this.company.set(c))
        .catch(() => {
          this.loading = null;
        });
    }
    return this.loading;
  }

  whatsappLink(number?: string, text = '') {
    const n = (number || this.company()?.whatsapp || '').replace(/\D/g, '');
    return n ? `https://wa.me/${n}${text ? `?text=${encodeURIComponent(text)}` : ''}` : '';
  }
}
