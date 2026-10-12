import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { Api } from '../core/api.service';
import { Auth, ROLE_LABELS } from '../core/auth.service';
import { CompanyStore } from '../core/company.service';
import { Icon } from '../shared/ui';

interface NavItem {
  path: string;
  label: string;
  icon: string;
  cap?: string;
}

const NAV: NavItem[] = [
  { path: '/management/dashboard', label: 'Dashboard', icon: 'home' },
  { path: '/management/properties', label: 'Properties & units', icon: 'building', cap: 'view_properties' },
  { path: '/management/tenants', label: 'Tenants', icon: 'users', cap: 'view_tenants' },
  { path: '/management/payments', label: 'Rent & payments', icon: 'wallet', cap: 'view_payments' },
  { path: '/management/leasing', label: 'Applications', icon: 'clipboard', cap: 'manage_applications' },
  { path: '/management/announcements', label: 'Announcements', icon: 'megaphone', cap: 'view_announcements' },
  { path: '/management/documents', label: 'Documents & rules', icon: 'file', cap: 'view_documents' },
  { path: '/management/maintenance', label: 'Maintenance', icon: 'wrench', cap: 'view_maintenance' },
  { path: '/management/reports', label: 'Reports', icon: 'chart', cap: 'view_reports' },
];
const ADMIN_NAV: NavItem[] = [
  { path: '/management/staff', label: 'Staff & access', icon: 'key', cap: 'manage_staff' },
  { path: '/management/settings', label: 'Settings', icon: 'settings' },
  { path: '/management/audit', label: 'Audit log', icon: 'shield', cap: 'view_audit' },
];

@Component({
  selector: 'app-management-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon],
  template: `
    <aside class="sidebar" [class.open]="menuOpen()">
      <div class="side-brand">
        <span class="brand-mark">{{ (company.company()?.name || 'P').charAt(0) }}</span>
        <div><div class="brand-name">{{ company.company()?.name || 'Property Manager' }}</div><div class="brand-sub">Management</div></div>
      </div>
      <nav>
        @for (item of nav(); track item.path) {
          <a [routerLink]="item.path" routerLinkActive="active"><app-icon [name]="item.icon" /> {{ item.label }}</a>
        }
        <div class="nav-sep">Administration</div>
        @for (item of adminNav(); track item.path) {
          <a [routerLink]="item.path" routerLinkActive="active"><app-icon [name]="item.icon" /> {{ item.label }}</a>
        }
      </nav>
      <div class="side-foot">
        <div class="scope">
          @if (auth.me()?.portfolio_access) { <span>Whole portfolio</span> }
          @else { <span>{{ auth.me()?.assigned_properties?.length }} assigned propert{{ auth.me()?.assigned_properties?.length === 1 ? 'y' : 'ies' }}</span> }
        </div>
        <a href="/" target="_blank" class="muted small">View public website ↗</a>
      </div>
    </aside>
    @if (menuOpen()) { <div class="scrim" (click)="menuOpen.set(false)"></div> }
    <div class="main">
      <header class="topbar">
        <button class="icon-btn menu-btn" (click)="menuOpen.set(true)" aria-label="Open menu"><app-icon name="menu" /></button>
        <div class="spacer"></div>
        <a class="icon-btn bell" routerLink="/management/notifications" aria-label="Notifications">
          <app-icon name="bell" />
          @if (unread() > 0) { <span class="dot">{{ unread() > 9 ? '9+' : unread() }}</span> }
        </a>
        <div class="user">
          <div class="avatar">{{ initials() }}</div>
          <div class="user-meta"><div class="strong">{{ auth.me()?.full_name }}</div><div class="muted small">{{ roleLabel() }}</div></div>
        </div>
        <button class="icon-btn" (click)="auth.logout()" title="Sign out" aria-label="Sign out"><app-icon name="logout" /></button>
      </header>
      @if (auth.me()?.must_change_password) {
        <div class="alert alert-warn banner">Please set a new password in <a routerLink="/management/settings">Settings → My account</a>.</div>
      }
      <main class="content"><router-outlet /></main>
    </div>
  `,
  styles: `
    :host { display: block; min-height: 100vh; }
    .sidebar { position: fixed; inset: 0 auto 0 0; width: var(--sidebar); background: #12302a; color: #cfdcd7; display: flex; flex-direction: column; z-index: 40; }
    .side-brand { display: flex; align-items: center; gap: 10px; padding: 18px 18px 16px; border-bottom: 1px solid rgba(255,255,255,.07); }
    .brand-mark { width: 34px; height: 34px; border-radius: 9px; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-display); font-size: 1.1rem; }
    .brand-name { color: #fff; font-weight: 650; font-size: .92rem; line-height: 1.2; }
    .brand-sub { font-size: .75rem; opacity: .65; }
    nav { flex: 1; overflow-y: auto; padding: 12px 10px; }
    nav a { display: flex; align-items: center; gap: 11px; padding: 9px 12px; border-radius: 8px; color: #cfdcd7; font-weight: 500; margin-bottom: 2px; text-decoration: none; }
    nav a:hover { background: rgba(255,255,255,.06); color: #fff; }
    nav a.active { background: rgba(255,255,255,.1); color: #fff; box-shadow: inset 3px 0 0 var(--accent); }
    .nav-sep { font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; opacity: .5; padding: 16px 12px 6px; }
    .side-foot { padding: 14px 18px; border-top: 1px solid rgba(255,255,255,.07); font-size: .8rem; }
    .side-foot a { color: #9fb5ad; }
    .scope { margin-bottom: 4px; color: #fff; }
    .main { margin-left: var(--sidebar); min-height: 100vh; display: flex; flex-direction: column; }
    .topbar { height: 60px; display: flex; align-items: center; gap: 10px; padding: 0 24px; background: #fff; border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 30; }
    .spacer { flex: 1; }
    .bell { position: relative; }
    .dot { position: absolute; top: 2px; right: 0; background: var(--red); color: #fff; font-size: .62rem; font-weight: 700; border-radius: 999px; padding: 0 5px; line-height: 15px; }
    .user { display: flex; align-items: center; gap: 10px; padding-left: 8px; }
    .avatar { width: 34px; height: 34px; border-radius: 50%; background: var(--brand-50); color: var(--brand); font-weight: 700; display: inline-flex; align-items: center; justify-content: center; font-size: .85rem; }
    .user-meta { line-height: 1.25; font-size: .85rem; }
    .content { padding: 26px 28px 48px; max-width: 1400px; width: 100%; }
    .banner { margin: 12px 28px 0; }
    .menu-btn { display: none; }
    .scrim { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 35; }
    @media (max-width: 960px) {
      .sidebar { transform: translateX(-100%); transition: transform .2s; }
      .sidebar.open { transform: none; }
      .main { margin-left: 0; }
      .menu-btn { display: inline-flex; }
      .content { padding: 18px 16px 40px; }
      .topbar { padding: 0 12px; }
      .user-meta { display: none; }
      .banner { margin: 12px 16px 0; }
    }
  `,
})
export class ManagementLayout {
  auth = inject(Auth);
  company = inject(CompanyStore);
  private api = inject(Api);
  menuOpen = signal(false);
  unread = signal(0);
  nav = computed(() => NAV.filter((i) => !i.cap || this.auth.me()?.capabilities.includes(i.cap)));
  adminNav = computed(() => ADMIN_NAV.filter((i) => !i.cap || this.auth.me()?.capabilities.includes(i.cap)));
  roleLabel = computed(() => ROLE_LABELS[this.auth.me()?.role ?? ''] ?? '');
  initials = computed(() => {
    const m = this.auth.me();
    return `${m?.first_name?.charAt(0) ?? ''}${m?.last_name?.charAt(0) ?? ''}`.toUpperCase() || '?';
  });

  constructor() {
    this.company.load();
    const router = inject(Router);
    const sub = router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => {
      this.menuOpen.set(false);
      this.pollUnread();
    });
    this.pollUnread();
    const timer = setInterval(() => this.pollUnread(), 60000);
    inject(DestroyRef).onDestroy(() => {
      clearInterval(timer);
      sub.unsubscribe();
    });
  }

  private pollUnread() {
    this.api.get('my-notifications/').subscribe({ next: (r) => this.unread.set(r.unread), error: () => {} });
  }
}
