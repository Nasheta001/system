import { Component, ElementRef, OnDestroy, effect, inject, input, output, viewChild } from '@angular/core';
import { CompanyStore } from '../core/company.service';

declare global {
  interface Window {
    turnstile?: { render: (el: HTMLElement, opts: any) => string; remove: (id: string) => void; reset: (id: string) => void };
  }
}

let scriptPromise: Promise<void> | null = null;
function loadTurnstile(): Promise<void> {
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => {
        scriptPromise = null;
        reject(new Error('Verification could not be loaded'));
      };
      document.head.appendChild(s);
    });
  }
  return scriptPromise;
}

/**
 * Bot protection for public forms:
 *  - a visually hidden honeypot input ("website") that people never fill in;
 *  - a Cloudflare Turnstile widget, shown only when the backend publishes a site key.
 * The server verifies both; this component only collects the values.
 */
@Component({
  selector: 'app-bot-guard',
  template: `
    <div class="hp" aria-hidden="true">
      <label>Website <input type="text" name="website" tabindex="-1" autocomplete="off" (input)="honeypot.emit($any($event.target).value)"></label>
    </div>
    @if (siteKey()) { <div #box class="turnstile"></div> }`,
  styles: `
    .hp { position: absolute; left: -10000px; top: auto; width: 1px; height: 1px; overflow: hidden; }
    .turnstile { margin: 6px 0 12px; min-height: 65px; }
  `,
})
export class BotGuard implements OnDestroy {
  private company = inject(CompanyStore);
  private box = viewChild<ElementRef<HTMLElement>>('box');
  token = output<string>();
  honeypot = output<string>();
  /** Increment to reset the widget after a failed submission. */
  resetKey = input(0);
  siteKey = () => this.company.company()?.turnstile_site_key || '';
  private widgetId = '';

  constructor() {
    this.company.load();
    effect(() => {
      const el = this.box()?.nativeElement;
      const key = this.siteKey();
      if (!el || !key || this.widgetId) return;
      loadTurnstile()
        .then(() => {
          this.widgetId = window.turnstile!.render(el, {
            sitekey: key,
            callback: (t: string) => this.token.emit(t),
            'expired-callback': () => this.token.emit(''),
            'error-callback': () => this.token.emit(''),
          });
        })
        .catch(() => this.token.emit(''));
    });
    effect(() => {
      if (this.resetKey() && this.widgetId) {
        window.turnstile?.reset(this.widgetId);
        this.token.emit('');
      }
    });
  }

  ngOnDestroy() {
    if (this.widgetId) window.turnstile?.remove(this.widgetId);
  }
}
