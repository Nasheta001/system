import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CompanyStore } from '../core/company.service';
import { Icon } from '../shared/ui';

@Component({
  selector: 'app-public-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon],
  template: `
    <header class="pub-header">
      <div class="pub-wrap pub-nav">
        <a routerLink="/" class="brand"><span class="brand-mark">{{ initial() }}</span>{{ company.company()?.name || 'Homes' }}</a>
        <button class="icon-btn menu-btn" (click)="open.set(!open())" aria-label="Menu"><app-icon [name]="open() ? 'x' : 'menu'" /></button>
        <nav [class.open]="open()" (click)="open.set(false)">
          <a routerLink="/properties" routerLinkActive="active">Properties</a>
          <a routerLink="/about" routerLinkActive="active">About & FAQ</a>
          <a routerLink="/application-status" routerLinkActive="active">Application status</a>
          <a routerLink="/login" class="btn btn-sm">Sign in</a>
        </nav>
      </div>
    </header>
    <main><router-outlet /></main>
    <footer class="pub-footer">
      <div class="pub-wrap footer-grid">
        <div>
          <div class="brand light"><span class="brand-mark">{{ initial() }}</span>{{ company.company()?.name }}</div>
          <p>{{ company.company()?.tagline }}</p>
        </div>
        <div>
          <h4>Contact</h4>
          @if (company.company()?.phone) { <a [href]="'tel:' + company.company()?.phone"><app-icon name="phone" [size]="14" /> {{ company.company()?.phone }}</a> }
          @if (company.company()?.email) { <a [href]="'mailto:' + company.company()?.email"><app-icon name="mail" [size]="14" /> {{ company.company()?.email }}</a> }
          @if (company.whatsappLink()) { <a [href]="company.whatsappLink()" target="_blank" rel="noopener"><app-icon name="chat" [size]="14" /> WhatsApp</a> }
        </div>
        <div>
          <h4>Links</h4>
          <a routerLink="/properties">Available homes</a>
          <a routerLink="/privacy">Privacy notice</a>
          <a routerLink="/tenant/login">Tenant sign in</a>
          <a routerLink="/management/login">Landlord / management sign in</a>
        </div>
      </div>
      <div class="pub-wrap copyright">© {{ year }} {{ company.company()?.name }}</div>
    </footer>
    <div class="tabbar" role="navigation" aria-label="Quick navigation">
      <a routerLink="/" routerLinkActive="on" [routerLinkActiveOptions]="{ exact: true }"><app-icon name="home" [size]="21" /><span>Home</span></a>
      <a routerLink="/properties" routerLinkActive="on"><app-icon name="search" [size]="21" /><span>Search</span></a>
      <a routerLink="/application-status" routerLinkActive="on"><app-icon name="clipboard" [size]="21" /><span>Status</span></a>
      <a routerLink="/about" routerLinkActive="on"><app-icon name="chat" [size]="21" /><span>Contact</span></a>
      <a routerLink="/login" routerLinkActive="on"><app-icon name="user" [size]="21" /><span>Sign in</span></a>
    </div>
  `,
  styles: `
    :host { display: flex; flex-direction: column; min-height: 100vh; background: #fbfaf8; }
    main { flex: 1; }
    .pub-header { background: #fff; border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 20; }
    .pub-nav { display: flex; align-items: center; justify-content: space-between; height: 64px; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.05rem; color: var(--ink); text-decoration: none; }
    .brand-mark { width: 32px; height: 32px; border-radius: 8px; background: var(--brand); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-display); }
    .brand.light { color: #fff; }
    nav { display: flex; align-items: center; gap: 22px; }
    nav a:not(.btn) { color: var(--ink-2); font-weight: 550; }
    nav a.active { color: var(--brand); }
    .menu-btn { display: none; }
    .tabbar { display: none; }
    .pub-footer { background: #15362e; color: #c9d6d1; padding: 40px 0 18px; margin-top: 48px; }
    .footer-grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 24px; }
    .pub-footer h4 { color: #fff; font-size: .9rem; margin-bottom: 10px; }
    .pub-footer a { display: flex; gap: 8px; align-items: center; color: #c9d6d1; margin-bottom: 6px; }
    .copyright { margin-top: 28px; font-size: .8rem; opacity: .7; }
    @media (max-width: 760px) {
      .menu-btn { display: inline-flex; }
      nav { display: none; position: absolute; top: 64px; left: 0; right: 0; background: #fff; flex-direction: column; align-items: stretch; padding: 12px 16px 18px; gap: 4px; border-bottom: 1px solid var(--line); box-shadow: var(--shadow); }
      nav.open { display: flex; }
      nav a:not(.btn) { padding: 10px 0; }
      .footer-grid { grid-template-columns: 1fr; }
      .pub-footer { padding-bottom: 86px; }
      .tabbar { display: grid; grid-template-columns: repeat(5, 1fr); position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
        background: rgba(255,255,255,.96); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
        border-top: 1px solid var(--line); padding: 6px 4px calc(6px + env(safe-area-inset-bottom)); }
      .tabbar a { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 4px 0; color: var(--muted); font-size: .7rem; font-weight: 600; text-decoration: none; }
      .tabbar a.on { color: #5b4fd6; }
    }
  `,
})
export class PublicLayout {
  company = inject(CompanyStore);
  open = signal(false);
  year = new Date().getFullYear();
  constructor() {
    this.company.load();
  }
  initial() {
    return (this.company.company()?.name || 'H').charAt(0);
  }
}
