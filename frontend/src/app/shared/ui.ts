import { Component, computed, effect, inject, input, model, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LabelPipe } from '../core/format';
import { Ui } from '../core/ui.service';

const ICONS: Record<string, string> = {
  home: 'M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  building: 'M4 21V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17M16 9h3a1 1 0 0 1 1 1v11M2 21h20M8 7h4M8 11h4M8 15h4',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  wallet: 'M3 7h18v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM3 7l2-3h14l2 3M16 13h2',
  megaphone: 'M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1zM17 8a5 5 0 0 1 0 8',
  wrench: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z',
  chart: 'M3 3v18h18M7 15l4-4 3 3 5-6',
  file: 'M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 13h6M9 17h6',
  key: 'M15 7a4 4 0 1 1-3.9 4.9L3 20v-3h3v-3h3l2.1-2.1A4 4 0 0 1 15 7z',
  settings: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M14 4v4M8 10v4M16 16v4',
  clipboard: 'M9 3h6v3H9zM7 4.5H5V21h14V4.5h-2M8 11h8M8 15h5',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  bell: 'M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4',
  logout: 'M9 21H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h4M16 17l5-5-5-5M21 12H9',
  menu: 'M3 6h18M3 12h18M3 18h18',
  x: 'M18 6 6 18M6 6l12 12',
  plus: 'M12 5v14M5 12h14',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3',
  pin: 'M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  bed: 'M3 18V6M3 14h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5M7 11a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3',
  phone: 'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z',
  mail: 'M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM3 6l9 7 9-7',
  chat: 'M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.6-5.2A8.5 8.5 0 1 1 21 12z',
  check: 'M20 6 9 17l-5-5',
  download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
  upload: 'M12 21V9M7 14l5-5 5 5M5 3h14',
  left: 'M19 12H5M12 19l-7-7 7-7',
  right: 'M5 12h14M12 5l7 7-7 7',
  calendar: 'M4 5h16v16H4zM4 9h16M8 3v4M16 3v4',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  layers: 'M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6',
  refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
  archive: 'M3 4h18v4H3zM5 8v12h14V8M10 12h4',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z',
  trash: 'M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6',
  copy: 'M8 8h12v12H8zM16 8V4H4v12h4',
  send: 'M22 2 11 13M22 2l-7 20-4-9-9-4z',
  receipt: 'M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2zM9 8h6M9 12h6M9 16h3',
  door: 'M4 21h16M6 21V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17M14 12h.01',
};

@Component({
  selector: 'app-icon',
  template: `<svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path [attr.d]="path()" /></svg>`,
  host: { class: 'icon' },
})
export class Icon {
  name = input.required<string>();
  size = input(18);
  path = computed(() => ICONS[this.name()] ?? '');
}

const BADGE_TONE: Record<string, string> = {
  available: 'green', verified: 'green', success: 'green', paid: 'green', completed: 'green', approved: 'green',
  published: 'green', active: 'green', delivered: 'green', done: 'green', credit: 'green', converted: 'green',
  sent: 'green', closed: 'grey',
  reserved: 'amber', pending: 'amber', under_review: 'amber', due: 'amber', notice: 'amber', scheduled: 'blue',
  assigned: 'blue', in_progress: 'blue', reviewed: 'blue', awaiting_parts: 'amber', submitted: 'blue', new: 'blue',
  contacted: 'blue', upcoming: 'blue', queued: 'blue', open: 'amber', high: 'amber', logged: 'grey',
  occupied: 'teal', overdue: 'red', failed: 'red', rejected: 'red', emergency: 'red', urgent: 'red',
  cancelled: 'grey', expired: 'grey', withdrawn: 'grey', archived: 'grey', ended: 'grey', former: 'grey',
  unavailable: 'grey', maintenance: 'amber', timeout: 'grey', draft: 'grey', skipped: 'grey', dismissed: 'grey',
  low: 'grey', normal: 'blue',
};

@Component({
  selector: 'app-badge',
  imports: [LabelPipe],
  template: `<span class="badge" [class]="'badge badge-' + tone()">{{ text() || (value() | label) }}</span>`,
})
export class Badge {
  value = input<string | null | undefined>('');
  text = input<string>('');
  tone = computed(() => BADGE_TONE[this.value() ?? ''] ?? 'grey');
}

@Component({
  selector: 'app-empty',
  imports: [Icon],
  template: `
    <div class="empty">
      <div class="empty-icon"><app-icon [name]="icon()" [size]="26" /></div>
      <h3>{{ title() }}</h3>
      @if (text()) { <p>{{ text() }}</p> }
      <ng-content />
    </div>`,
})
export class Empty {
  icon = input('layers');
  title = input.required<string>();
  text = input('');
}

@Component({
  selector: 'app-page-header',
  imports: [RouterLink, Icon],
  template: `
    <div class="page-header">
      <div>
        @if (back()) { <a class="back-link" [routerLink]="back()"><app-icon name="left" [size]="16" /> {{ backLabel() }}</a> }
        <h1>{{ title() }}</h1>
        @if (subtitle()) { <p class="muted">{{ subtitle() }}</p> }
      </div>
      <div class="page-actions"><ng-content /></div>
    </div>`,
})
export class PageHeader {
  title = input.required<string>();
  subtitle = input('');
  back = input<string | any[] | null>(null);
  backLabel = input('Back');
}

@Component({
  selector: 'app-modal',
  imports: [Icon],
  template: `
    @if (open()) {
      <div class="modal-backdrop" (click)="close()"></div>
      <div class="modal" [class.modal-wide]="wide()" role="dialog" aria-modal="true" [attr.aria-label]="title()">
        <div class="modal-head">
          <h2>{{ title() }}</h2>
          <button type="button" class="icon-btn" (click)="close()" aria-label="Close"><app-icon name="x" /></button>
        </div>
        <div class="modal-body"><ng-content /></div>
      </div>
    }`,
})
export class Modal {
  open = model(false);
  title = input('');
  wide = input(false);
  closed = output<void>();
  close() {
    this.open.set(false);
    this.closed.emit();
  }
}

@Component({
  selector: 'app-pager',
  template: `
    @if (count() > pageSize()) {
      <div class="pager">
        <span class="muted">{{ from() }}–{{ to() }} of {{ count() }}</span>
        <button class="btn btn-sm" [disabled]="page() <= 1" (click)="page.set(page() - 1)">Previous</button>
        <button class="btn btn-sm" [disabled]="to() >= count()" (click)="page.set(page() + 1)">Next</button>
      </div>
    }`,
})
export class Pager {
  count = input(0);
  pageSize = input(25);
  page = model(1);
  from = computed(() => (this.page() - 1) * this.pageSize() + 1);
  to = computed(() => Math.min(this.page() * this.pageSize(), this.count()));
}

@Component({
  selector: 'app-stat',
  imports: [Icon, RouterLink],
  template: `
    <a class="stat" [routerLink]="link()" [class.stat-static]="!link()">
      <div class="stat-top"><span class="stat-label">{{ label() }}</span>
        @if (icon()) { <span class="stat-icon" [class]="'stat-icon tone-' + tone()"><app-icon [name]="icon()" [size]="16" /></span> }
      </div>
      <div class="stat-value">{{ value() }}</div>
      @if (hint()) { <div class="stat-hint">{{ hint() }}</div> }
    </a>`,
})
export class Stat {
  label = input.required<string>();
  value = input<string | number | null>('—');
  hint = input('');
  icon = input('');
  tone = input('green');
  link = input<string | any[] | null>(null);
}

@Component({
  selector: 'app-toasts',
  template: `
    <div class="toasts" aria-live="polite">
      @for (t of ui.toasts(); track t.id) {
        <div class="toast" [class]="'toast toast-' + t.kind" (click)="ui.dismiss(t.id)">{{ t.text }}</div>
      }
    </div>`,
})
export class ToastHost {
  ui = inject(Ui);
}

@Component({
  selector: 'app-confirm',
  imports: [FormsModule],
  template: `
    @if (ui.confirmRequest(); as req) {
      <div class="modal-backdrop" (click)="ui.answer(req.reasonLabel ? null : false)"></div>
      <div class="modal modal-sm" role="alertdialog" aria-modal="true">
        <div class="modal-head"><h2>{{ req.title }}</h2></div>
        <div class="modal-body">
          <p>{{ req.message }}</p>
          @if (req.reasonLabel) {
            <label class="field"><span>{{ req.reasonLabel }}</span>
              <textarea rows="3" [(ngModel)]="reason" name="reason"></textarea></label>
          }
          <div class="form-actions">
            <button class="btn" type="button" (click)="ui.answer(req.reasonLabel ? null : false)">Cancel</button>
            <button class="btn" type="button" [class.btn-danger]="req.danger" [class.btn-primary]="!req.danger"
              [disabled]="!!req.reasonLabel && !reason().trim()"
              (click)="ui.answer(req.reasonLabel ? reason().trim() : true)">{{ req.confirmText || 'Confirm' }}</button>
          </div>
        </div>
      </div>
    }`,
})
export class ConfirmHost {
  ui = inject(Ui);
  reason = signal('');
  constructor() {
    effect(() => {
      if (this.ui.confirmRequest()) this.reason.set('');
    });
  }
}

@Component({
  selector: 'app-loading',
  template: `<div class="loading" role="status"><span class="spinner"></span> {{ text() }}</div>`,
})
export class Loading {
  text = input('Loading…');
}
