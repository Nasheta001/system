import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { CompanyStore } from '../../core/company.service';
import { Icon } from '../../shared/ui';

/** /login – choose the right sign-in. There is no public registration. */
@Component({
  imports: [RouterLink, Icon],
  template: `
    <div class="pub-wrap narrow-page">
      <h1>Sign in</h1>
      <p class="muted">Choose how you use {{ company.company()?.name || 'the system' }}. Accounts are created by invitation only.</p>
      <div class="choices">
        <a class="card card-pad choice" routerLink="/tenant/login">
          <app-icon name="home" [size]="26" />
          <h2>Tenant</h2>
          <p class="muted small">Pay rent, download receipts, read notices and report repairs.</p>
          <span class="btn btn-primary">Tenant sign in</span>
        </a>
        <a class="card card-pad choice" routerLink="/management/login">
          <app-icon name="building" [size]="26" />
          <h2>Landlord / Management</h2>
          <p class="muted small">For landlords, administrators, property managers and caretakers.</p>
          <span class="btn">Management sign in</span>
        </a>
      </div>
      <p class="muted small mt">New tenant? Your landlord or property manager sends you an email invitation once your tenancy is set up.
        Staff accounts are created by a company administrator.</p>
    </div>`,
  styles: `
    .choices { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin-top: 16px; }
    .choice { display: flex; flex-direction: column; gap: 6px; text-decoration: none; color: inherit; }
    .choice:hover { border-color: var(--brand); }
    .choice h2 { margin: 4px 0 0; font-size: 1.15rem; }
    .choice .btn { margin-top: auto; align-self: flex-start; }
  `,
})
export class LoginChooserPage {
  company = inject(CompanyStore);
  constructor() {
    this.company.load();
  }
}

/** /account/accept-invite#token=… – the token is in the URL fragment, which browsers never send to the server. */
@Component({
  imports: [FormsModule, RouterLink, DatePipe],
  template: `
    <div class="pub-wrap narrow-page">
      <div class="card card-pad">
        @if (state() === 'loading') { <p class="muted">Checking your invitation…</p> }
        @else if (state() === 'invalid') {
          <h1>Invitation not valid</h1>
          <div class="alert alert-error">{{ error() }}</div>
          <p class="muted">Invitations work once and expire. Ask your landlord, property manager or company administrator to send a new one.</p>
          <a routerLink="/login">Go to sign in</a>
        } @else if (state() === 'done') {
          <h1>Your account is ready</h1>
          <div class="alert alert-success">You can now sign in with {{ info()?.email }} and your new password.</div>
          <a class="btn btn-primary" [routerLink]="portal() === 'tenant' ? '/tenant/login' : '/management/login'">Sign in</a>
        } @else {
          <h1>Accept your invitation</h1>
          <p class="muted">{{ info()?.company }} invited <b>{{ info()?.email }}</b>
            {{ info()?.kind === 'tenant' ? 'to the tenant portal.' : 'as ' + info()?.role_label + '.' }}
            This link expires on {{ info()?.expires_at | date: 'd MMM yyyy, HH:mm' }}.</p>
          @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
          <form (ngSubmit)="accept()">
            <p class="muted small">Choose a password of at least 10 characters. Avoid common words or only numbers.</p>
            <label class="field"><span>New password</span><input type="password" name="p1" [(ngModel)]="p1" autocomplete="new-password" required></label>
            <label class="field" [class.invalid]="p2 && p1 !== p2"><span>Confirm password</span>
              <input type="password" name="p2" [(ngModel)]="p2" autocomplete="new-password" required>
              @if (p2 && p1 !== p2) { <small class="error-text">Passwords do not match.</small> }
            </label>
            <button class="btn btn-primary btn-block" [disabled]="busy() || !p1 || p1 !== p2">Create my account</button>
          </form>
        }
      </div>
    </div>`,
})
export class AcceptInvitePage {
  private api = inject(Api);
  state = signal<'loading' | 'ready' | 'invalid' | 'done'>('loading');
  info = signal<any>(null);
  portal = signal('');
  error = signal('');
  busy = signal(false);
  p1 = '';
  p2 = '';
  private token = '';

  constructor() {
    const fragment = inject(ActivatedRoute).snapshot.fragment || '';
    this.token = new URLSearchParams(fragment).get('token') || '';
    // Remove the secret from the address bar and browser history.
    if (this.token) history.replaceState(history.state, '', location.pathname);
    this.check();
  }

  private async check() {
    if (!this.token) {
      this.error.set('This link is incomplete.');
      this.state.set('invalid');
      return;
    }
    try {
      this.info.set(await this.api.postP('auth/invitations/check/', { token: this.token }));
      this.state.set('ready');
    } catch (e) {
      this.error.set(parseError(e).message);
      this.state.set('invalid');
    }
  }

  async accept() {
    this.busy.set(true);
    this.error.set('');
    try {
      const r = await this.api.postP('auth/invitations/accept/', { token: this.token, password: this.p1 });
      this.portal.set(r.portal);
      this.state.set('done');
    } catch (e) {
      const err = parseError(e);
      this.error.set(err.fields['password'] || err.message);
    } finally {
      this.busy.set(false);
    }
  }
}

/** /account/setup – create the first administrator. The API refuses once any administrator exists. */
@Component({
  imports: [FormsModule, RouterLink],
  template: `
    <div class="pub-wrap narrow-page">
      <div class="card card-pad">
        <h1>First-time setup</h1>
        @if (status() === null) { <p class="muted">Checking…</p> }
        @else if (done()) {
          <div class="alert alert-success">Administrator account created.</div>
          <a class="btn btn-primary" routerLink="/management/login">Sign in</a>
        } @else if (!status().setup_required) {
          <div class="alert alert-info">Setup is complete. New staff join by invitation from an administrator.</div>
          <a routerLink="/management/login">Management sign in</a>
        } @else if (!status().available) {
          <div class="alert alert-warn">Website setup is disabled on this server. Create the first administrator on the server with
            <code>manage.py createsuperuser</code>, or set <code>SETUP_TOKEN</code>.</div>
        } @else {
          <p class="muted">No administrator exists yet. Create the company administrator account. This page stops working as soon as it is used.</p>
          @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
          <form (ngSubmit)="save()">
            <div class="form-grid">
              <label class="field"><span>First name</span><input name="fn" [(ngModel)]="f.first_name" required></label>
              <label class="field"><span>Last name</span><input name="ln" [(ngModel)]="f.last_name"></label>
            </div>
            <label class="field"><span>Email</span><input type="email" name="e" [(ngModel)]="f.email" autocomplete="username" required></label>
            <label class="field"><span>Password (10+ characters)</span><input type="password" name="p" [(ngModel)]="f.password" autocomplete="new-password" required></label>
            @if (status().token_required) {
              <label class="field"><span>Setup token</span><input type="password" name="t" [(ngModel)]="f.setup_token" autocomplete="off" required>
                <small>The SETUP_TOKEN value configured on the server.</small></label>
            }
            <button class="btn btn-primary btn-block" [disabled]="busy() || !f.email || !f.first_name || !f.password">Create administrator</button>
          </form>
        }
      </div>
    </div>`,
})
export class InitialSetupPage {
  private api = inject(Api);
  status = signal<any>(null);
  done = signal(false);
  busy = signal(false);
  error = signal('');
  f = { first_name: '', last_name: '', email: '', password: '', setup_token: '' };

  constructor() {
    this.api.getP('auth/setup/').then((s) => this.status.set(s)).catch(() => this.status.set({ setup_required: false }));
  }

  async save() {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.postP('auth/setup/', this.f);
      this.done.set(true);
    } catch (e) {
      const err = parseError(e);
      this.error.set(err.fields['password'] || err.fields['email'] || err.message);
    } finally {
      this.busy.set(false);
    }
  }
}
