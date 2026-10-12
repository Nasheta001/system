import { Injectable, signal } from '@angular/core';

export interface Toast {
  id: number;
  kind: 'success' | 'error' | 'info';
  text: string;
}

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
  /** When set, the user must type a reason, which is passed to the resolver. */
  reasonLabel?: string;
  resolve: (value: any) => void;
}

@Injectable({ providedIn: 'root' })
export class Ui {
  readonly toasts = signal<Toast[]>([]);
  readonly confirmRequest = signal<ConfirmRequest | null>(null);
  private seq = 0;

  toast(text: string, kind: Toast['kind'] = 'success', ms = 4500) {
    const id = ++this.seq;
    this.toasts.update((t) => [...t, { id, kind, text }]);
    setTimeout(() => this.dismiss(id), ms);
  }
  error(text: string) {
    this.toast(text, 'error', 7000);
  }
  dismiss(id: number) {
    this.toasts.update((t) => t.filter((x) => x.id !== id));
  }

  /** Resolves true/false, or the typed reason when reasonLabel is set (null if cancelled). */
  confirm(opts: Omit<ConfirmRequest, 'resolve'>): Promise<any> {
    return new Promise((resolve) => this.confirmRequest.set({ ...opts, resolve }));
  }
  answer(value: any) {
    const req = this.confirmRequest();
    this.confirmRequest.set(null);
    req?.resolve(value);
  }
}
