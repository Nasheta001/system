import { Component, inject, input, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { CompanyStore } from '../../core/company.service';

@Component({
  selector: 'app-login-form',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="auth-page" [class.tenant]="portal() === 'tenant'">
      <!-- decorative layered mountains -->
      <svg class="scenery" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="lg-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b1640"/><stop offset="1" stop-color="#0d0b1f"/></linearGradient>
          <linearGradient id="lg-m1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3b2a7a"/><stop offset="1" stop-color="#1f5a8a"/></linearGradient>
          <linearGradient id="lg-m2" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2a1d5c"/><stop offset="1" stop-color="#4a2368"/></linearGradient>
        </defs>
        <rect width="1440" height="900" fill="url(#lg-sky)"/>
        <path d="M0 260 L180 120 L340 230 L520 70 L700 210 L880 90 L1060 240 L1240 110 L1440 220 V900 H0Z" fill="url(#lg-m1)" opacity=".55"/>
        <path d="M0 340 L220 210 L410 320 L600 190 L820 330 L1010 200 L1210 320 L1440 240 V900 H0Z" fill="url(#lg-m2)" opacity=".7"/>
        <path d="M0 430 L260 330 L480 420 L720 310 L960 420 L1180 330 L1440 400 V900 H0Z" fill="#14112b" opacity=".9"/>
        <path d="M0 260 L180 120 L340 230 L520 70 L700 210 L880 90 L1060 240 L1240 110 L1440 220" fill="none" stroke="#7c5cff" stroke-opacity=".35" stroke-width="1.5"/>
      </svg>

      <form class="auth-card" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <a routerLink="/" class="logo" [attr.aria-label]="company.company()?.name || 'Home'">
          <span class="logo-ring"><span class="logo-gem">{{ (company.company()?.name || 'H').charAt(0) }}</span></span>
          <span class="logo-name">{{ company.company()?.name || 'Property portal' }}</span>
        </a>

        <nav class="portal-switch" aria-label="Choose sign-in">
          <a routerLink="/tenant/login" [class.active]="portal() === 'tenant'">Tenant</a>
          <a routerLink="/management/login" [class.active]="portal() === 'management'">Landlord / Management</a>
        </nav>

        <h1>{{ portal() === 'tenant' ? 'Welcome home' : 'Welcome back' }}</h1>
        <p class="sub">{{ portal() === 'tenant' ? 'Sign in to pay rent, get receipts and report repairs.' : 'Sign in to manage properties, tenants and rent.' }}</p>
        @if (error()) { <div class="alert alert-error" role="alert">{{ error() }}</div> }

        <label class="fld" [class.invalid]="touched('email')">
          <span class="lbl">Email address</span>
          <span class="box">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>
            <input type="email" formControlName="email" autocomplete="username" placeholder="yourname@email.com" autofocus>
          </span>
          @if (touched('email')) { <small class="err">Enter a valid email.</small> }
        </label>

        <label class="fld" [class.invalid]="touched('password')">
          <span class="lbl">Password</span>
          <span class="box">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
            <input [type]="showPw() ? 'text' : 'password'" formControlName="password" autocomplete="current-password" placeholder="••••••••">
            <button type="button" class="eye" (click)="showPw.set(!showPw())" [attr.aria-label]="showPw() ? 'Hide password' : 'Show password'" [class.on]="showPw()">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>@if (showPw()) { <path d="M4 4l16 16"/> }</svg>
            </button>
          </span>
        </label>

        <div class="row-opts">
          <label class="remember"><input type="checkbox" formControlName="remember"> Keep me signed in</label>
          <a routerLink="/account/forgot-password" class="forgot">Forgot password?</a>
        </div>

        <button class="go" type="submit" [disabled]="busy()">
          <span>{{ busy() ? 'Signing in…' : 'Sign in' }}</span>
          @if (!busy()) { <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg> }
        </button>

        <div class="or-line"><span>invitation only</span></div>
        <p class="note">{{ portal() === 'tenant'
          ? 'New tenant? Your landlord or property manager emails you an invitation once your tenancy is set up.'
          : 'Staff accounts are created by invitation from a company administrator.' }}</p>
        @if (portal() === 'management' && setupAvailable()) {
          <div class="alert alert-info small">No administrator exists yet. <a routerLink="/account/setup">Run first-time setup</a>.</div>
        }
        <p class="secure">Protected area · activity is logged</p>
      </form>
    </div>
  `,
  styles: `
    :host { display: block; }
    .auth-page { position: relative; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 40px 16px; overflow: hidden; background: #0d0b1f; color: #e7e4f7; }
    .scenery { position: absolute; inset: 0; width: 100%; height: 100%; }
    .auth-page::after { content: ''; position: absolute; inset: auto 0 0 0; height: 45%; background: linear-gradient(180deg, transparent, rgba(124, 92, 255, .12)); pointer-events: none; }

    .auth-card { position: relative; z-index: 1; width: min(420px, 100%); padding: 34px 32px 26px; border-radius: 22px;
      background: linear-gradient(160deg, rgba(255,255,255,.09), rgba(255,255,255,.03));
      border: 1px solid rgba(255,255,255,.12); box-shadow: 0 30px 80px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.08);
      backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); }

    .logo { display: flex; flex-direction: column; align-items: center; gap: 10px; text-decoration: none; margin-bottom: 18px; }
    .logo-ring { width: 64px; height: 64px; border-radius: 50%; display: grid; place-items: center;
      background: radial-gradient(circle, rgba(124,92,255,.25), transparent 70%); border: 1.5px solid rgba(160,130,255,.55); box-shadow: 0 0 30px rgba(124,92,255,.35); }
    .logo-gem { width: 34px; height: 34px; border-radius: 9px; transform: rotate(45deg); display: grid; place-items: center;
      background: linear-gradient(135deg, #a855f7, #22d3ee); color: #fff; font-weight: 700; font-family: var(--font-display); }
    .logo-gem { font-size: 0; }
    .logo-gem::after { content: ''; width: 12px; height: 12px; border-radius: 4px; background: #1b1640; }
    .logo-name { color: #fff; letter-spacing: .18em; text-transform: uppercase; font-weight: 700; font-size: .82rem; text-align: center; }

    .portal-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border-radius: 12px; background: rgba(0,0,0,.28); border: 1px solid rgba(255,255,255,.07); margin-bottom: 20px; }
    .portal-switch a { display: flex; align-items: center; justify-content: center; text-align: center; padding: 9px 6px; border-radius: 9px; text-decoration: none; color: #a9a3c9; font-weight: 600; font-size: .85rem; transition: background .2s, color .2s; }
    .portal-switch a:hover { color: #fff; }
    .portal-switch a.active { color: #fff; background: linear-gradient(135deg, rgba(168,85,247,.55), rgba(34,211,238,.4)); box-shadow: 0 6px 18px rgba(124,92,255,.3); }

    h1 { margin: 0; text-align: center; color: #fff; font-family: var(--font-display); font-size: 1.75rem; font-weight: 700; }
    .sub { margin: 6px 0 20px; text-align: center; color: #a9a3c9; font-size: .92rem; }

    .fld { display: block; margin-bottom: 16px; }
    .lbl { display: block; font-size: .82rem; font-weight: 600; color: #d9d5ee; margin-bottom: 7px; }
    .box { display: flex; align-items: center; gap: 10px; padding: 0 12px; height: 48px; border-radius: 12px;
      background: rgba(0,0,0,.28); border: 1px solid rgba(255,255,255,.1); transition: border-color .2s, box-shadow .2s; }
    .box:focus-within { border-color: #8b6cff; box-shadow: 0 0 0 3px rgba(139,108,255,.25); }
    .invalid .box { border-color: #f87171; }
    .box svg { width: 19px; height: 19px; flex: none; fill: none; stroke: #8f88b5; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
    .box input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; background: transparent; color: #fff; font: inherit; font-size: .95rem; padding: 0; box-shadow: none; }
    .box input::placeholder { color: #6f6994; }
    .box input:-webkit-autofill { -webkit-text-fill-color: #fff; -webkit-box-shadow: 0 0 0 1000px #1d1938 inset; caret-color: #fff; }
    .eye { background: none; border: 0; padding: 4px; cursor: pointer; display: grid; place-items: center; border-radius: 6px; }
    .eye:hover svg, .eye.on svg { stroke: #c4b5fd; }
    .err { display: block; margin-top: 6px; color: #fca5a5; font-size: .8rem; }

    .row-opts { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin: 2px 0 20px; font-size: .84rem; flex-wrap: wrap; }
    .remember { display: inline-flex; align-items: center; gap: 8px; color: #c9c4e3; cursor: pointer; }
    .remember input { accent-color: #8b6cff; width: 16px; height: 16px; }
    .forgot { color: #38d9f5; font-weight: 600; text-decoration: none; }
    .forgot:hover { text-decoration: underline; }

    .go { width: 100%; height: 50px; border: 0; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px;
      color: #fff; font: inherit; font-weight: 700; font-size: 1rem; letter-spacing: .02em;
      background: linear-gradient(90deg, #8b5cf6 0%, #a855f7 35%, #22d3ee 100%); box-shadow: 0 10px 28px rgba(139,92,246,.4); transition: transform .15s, box-shadow .2s, filter .2s; }
    .go:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 14px 34px rgba(139,92,246,.5); filter: brightness(1.06); }
    .go:disabled { opacity: .7; cursor: progress; }
    .go svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

    .or-line { display: flex; align-items: center; gap: 12px; margin: 22px 0 10px; color: #8f88b5; font-size: .75rem; text-transform: uppercase; letter-spacing: .12em; }
    .or-line::before, .or-line::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,.18), transparent); }
    .note { margin: 0; text-align: center; color: #a9a3c9; font-size: .84rem; line-height: 1.5; }
    .secure { margin: 16px 0 0; text-align: center; color: #6f6994; font-size: .74rem; }
    .auth-card .alert { margin-bottom: 14px; }
    .auth-card .alert-info a { color: inherit; font-weight: 600; }

    @media (max-width: 480px) {
      .auth-page { padding: 24px 12px; align-items: flex-start; }
      .auth-card { padding: 26px 20px 20px; border-radius: 18px; }
      h1 { font-size: 1.5rem; }
    }
    @media (prefers-reduced-motion: reduce) { .go, .box, .portal-switch a { transition: none; } }
  `,
})
export class LoginForm {
  portal = input.required<'management' | 'tenant'>();
  company = inject(CompanyStore);
  private auth = inject(Auth);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  busy = signal(false);
  showPw = signal(false);
  error = signal('');
  form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
    remember: [true],
  });

  setupAvailable = signal(false);
  private api = inject(Api);

  constructor() {
    this.company.load();
    this.api.getP('auth/setup/').then((s) => this.setupAvailable.set(!!s.available)).catch(() => null);
  }

  touched(name: 'email' | 'password') {
    const c = this.form.controls[name];
    return c.invalid && c.touched;
  }

  async submit() {
    this.form.markAllAsTouched();
    if (this.form.invalid) return;
    this.busy.set(true);
    this.error.set('');
    const { email, password, remember } = this.form.getRawValue();
    try {
      await this.auth.login(email, password, this.portal(), remember);
      const next = this.route.snapshot.queryParamMap.get('next');
      const base = this.portal() === 'tenant' ? '/tenant' : '/management';
      this.router.navigateByUrl(next && next.startsWith(base) ? next : `${base}/dashboard`);
    } catch (e) {
      this.error.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }
}

@Component({ imports: [LoginForm], template: `<app-login-form portal="management" />` })
export class ManagementLogin {}

@Component({ imports: [LoginForm], template: `<app-login-form portal="tenant" />` })
export class TenantLogin {}
