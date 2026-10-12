import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { BotGuard } from '../../shared/bot-guard';

@Component({
  imports: [FormsModule, RouterLink, BotGuard],
  template: `
    <div class="pub-wrap narrow-page">
      <div class="card card-pad">
        <h1>Forgot your password?</h1>
        @if (sent()) {
          <div class="alert alert-success">If that email is registered, we have sent a link to reset your password. The link is valid for 3 days.</div>
          <a routerLink="/tenant/login">Back to sign in</a>
        } @else {
          <p class="muted">Enter your account email and we will send you a secure reset link.</p>
          @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
          <form (ngSubmit)="submit()">
            <label class="field"><span>Email address</span><input type="email" name="email" [(ngModel)]="email" required></label>
            <app-bot-guard (token)="captcha = $event" (honeypot)="website = $event" [resetKey]="attempts()" />
            <button class="btn btn-primary btn-block" [disabled]="busy() || !email">Send reset link</button>
          </form>
        }
      </div>
    </div>`,
})
export class ForgotPasswordPage {
  private api = inject(Api);
  email = '';
  captcha = '';
  website = '';
  attempts = signal(0);
  busy = signal(false);
  sent = signal(false);
  error = signal('');

  async submit() {
    this.busy.set(true);
    try {
      await this.api.postP('auth/password/reset/', { email: this.email, captcha_token: this.captcha, website: this.website });
      this.sent.set(true);
    } catch (e) {
      this.error.set(parseError(e).message);
      this.attempts.update((n) => n + 1);
    } finally {
      this.busy.set(false);
    }
  }
}

@Component({
  imports: [FormsModule, RouterLink],
  template: `
    <div class="pub-wrap narrow-page">
      <div class="card card-pad">
        <h1>Set a new password</h1>
        @if (done()) {
          <div class="alert alert-success">Your password has been updated.</div>
          <a class="btn btn-primary" [routerLink]="role() === 'tenant' ? '/tenant/login' : '/management/login'">Sign in</a>
        } @else if (!uid() || !token()) {
          <div class="alert alert-error">This link is incomplete. Request a new one.</div>
          <a routerLink="/account/forgot-password">Request a new link</a>
        } @else {
          <p class="muted">Use at least 10 characters. Avoid common words or only numbers.</p>
          @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
          <form (ngSubmit)="submit()">
            <label class="field"><span>New password</span><input type="password" name="p1" [(ngModel)]="p1" autocomplete="new-password" required></label>
            <label class="field" [class.invalid]="p2 && p1 !== p2"><span>Confirm password</span>
              <input type="password" name="p2" [(ngModel)]="p2" autocomplete="new-password" required>
              @if (p2 && p1 !== p2) { <small class="error-text">Passwords do not match.</small> }
            </label>
            <button class="btn btn-primary btn-block" [disabled]="busy() || !p1 || p1 !== p2">Save password</button>
          </form>
        }
      </div>
    </div>`,
})
export class ResetPasswordPage {
  private api = inject(Api);
  uid = input<string>('');
  token = input<string>('');
  p1 = '';
  p2 = '';
  busy = signal(false);
  done = signal(false);
  role = signal('');
  error = signal('');

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      const r = await this.api.postP('auth/password/reset/confirm/', { uid: this.uid(), token: this.token(), new_password: this.p1 });
      this.role.set(r.role);
      this.done.set(true);
    } catch (e) {
      const err = parseError(e);
      this.error.set(err.fields['new_password'] || err.message);
    } finally {
      this.busy.set(false);
    }
  }
}
