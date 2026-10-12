import { Component, DestroyRef, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { Api } from '../core/api.service';
import { Auth } from '../core/auth.service';
import { CompanyStore } from '../core/company.service';
import { Icon } from '../shared/ui';

@Component({
  selector: 'app-tenant-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon],
  template: `
    <header class="t-header">
      <div class="t-wrap t-bar">
        <a routerLink="/tenant/dashboard" class="brand"><span class="brand-mark">{{ (company.company()?.name || 'H').charAt(0) }}</span>
          <span class="brand-text">{{ company.company()?.name }}<small>Tenant portal</small></span></a>
        <nav class="top-nav">
          <a routerLink="/tenant/dashboard" routerLinkActive="active">Home</a>
          <a routerLink="/tenant/payments" routerLinkActive="active">Rent & payments</a>
          <a routerLink="/tenant/announcements" routerLinkActive="active">Notices @if (unread() > 0) {<span class="pill">{{ unread() }}</span>}</a>
          <a routerLink="/tenant/documents" routerLinkActive="active">Documents</a>
          <a routerLink="/tenant/maintenance" routerLinkActive="active">Maintenance</a>
        </nav>
        <div class="row" style="gap:4px">
          <a routerLink="/tenant/profile" class="icon-btn" aria-label="My profile"><app-icon name="user" /></a>
          <button class="icon-btn" (click)="auth.logout()" aria-label="Sign out"><app-icon name="logout" /></button>
        </div>
      </div>
    </header>
    <main class="t-wrap t-main"><router-outlet /></main>
    <nav class="bottom-nav" aria-label="Tenant navigation">
      <a routerLink="/tenant/dashboard" routerLinkActive="active"><app-icon name="home" /><span>Home</span></a>
      <a routerLink="/tenant/payments" routerLinkActive="active"><app-icon name="wallet" /><span>Pay</span></a>
      <a routerLink="/tenant/announcements" routerLinkActive="active"><app-icon name="megaphone" /><span>Notices</span>
        @if (unread() > 0) { <i class="badge-dot"></i> }</a>
      <a routerLink="/tenant/documents" routerLinkActive="active"><app-icon name="file" /><span>Docs</span></a>
      <a routerLink="/tenant/maintenance" routerLinkActive="active"><app-icon name="wrench" /><span>Repairs</span></a>
    </nav>
  `,
  styles: `
    :host { display: block; min-height: 100vh; background: #f6f5f2; }
    .t-wrap { max-width: 1040px; margin: 0 auto; padding: 0 16px; }
    .t-header { background: #fff; border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 20; }
    .t-bar { height: 62px; display: flex; align-items: center; gap: 16px; }
    .brand { display: flex; align-items: center; gap: 10px; color: var(--ink); text-decoration: none; }
    .brand-mark { width: 32px; height: 32px; border-radius: 8px; background: var(--brand); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-display); }
    .brand-text { font-weight: 650; font-size: .92rem; line-height: 1.15; display: flex; flex-direction: column; }
    .brand-text small { font-weight: 500; color: var(--muted); font-size: .72rem; }
    .top-nav { display: flex; gap: 4px; flex: 1; justify-content: center; }
    .top-nav a { padding: 8px 12px; border-radius: 8px; color: var(--ink-2); font-weight: 550; text-decoration: none; }
    .top-nav a.active { background: var(--brand-50); color: var(--brand); }
    .pill { background: var(--red); color: #fff; border-radius: 999px; font-size: .68rem; padding: 0 6px; margin-left: 4px; }
    .t-main { padding-top: 22px; padding-bottom: 90px; }
    .bottom-nav { display: none; }
    @media (max-width: 820px) {
      .top-nav { display: none; }
      .t-bar { justify-content: space-between; }
      .bottom-nav { display: flex; position: fixed; bottom: 0; left: 0; right: 0; background: #fff; border-top: 1px solid var(--line); z-index: 20; padding-bottom: env(safe-area-inset-bottom); }
      .bottom-nav a { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 0 7px; color: var(--muted); font-size: .7rem; font-weight: 600; text-decoration: none; position: relative; }
      .bottom-nav a.active { color: var(--brand); }
      .badge-dot { position: absolute; top: 6px; right: calc(50% - 16px); width: 8px; height: 8px; border-radius: 50%; background: var(--red); }
    }
  `,
})
export class TenantLayout {
  auth = inject(Auth);
  company = inject(CompanyStore);
  private api = inject(Api);
  unread = signal(0);

  constructor() {
    this.company.load();
    const refresh = () =>
      this.api.get('portal/announcements/', { page_size: 100 }).subscribe({
        next: (r: any) => this.unread.set(r.results.filter((a: any) => !a.opened_at).length),
        error: () => {},
      });
    refresh();
    const sub = inject(Router).events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(refresh);
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }
}
