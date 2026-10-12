import { Component, inject, signal } from '@angular/core';
import { CompanyStore } from '../../core/company.service';
import { Icon } from '../../shared/ui';

@Component({
  imports: [Icon],
  template: `
    <div class="pub-wrap section">
      <div class="split">
        <div>
          <h1 class="display">About {{ c()?.name }}</h1>
          <p style="white-space:pre-line">{{ c()?.about }}</p>
          <h2 class="mt">Frequently asked questions</h2>
          <div class="faq">
            @for (q of c()?.faq ?? []; track $index) {
              <div class="faq-item" [class.open]="open() === $index">
                <button type="button" (click)="open.set(open() === $index ? -1 : $index)" [attr.aria-expanded]="open() === $index">
                  {{ q.question }}<app-icon [name]="open() === $index ? 'x' : 'plus'" [size]="16" /></button>
                @if (open() === $index) { <p>{{ q.answer }}</p> }
              </div>
            }
          </div>
        </div>
        <aside class="card card-pad contact-card">
          <h3>Contact us</h3>
          @if (c()?.address) { <p class="row" style="gap:8px"><app-icon name="pin" [size]="16" /> {{ c()?.address }}</p> }
          @if (c()?.phone) { <a [href]="'tel:' + c()?.phone"><app-icon name="phone" [size]="16" /> {{ c()?.phone }}</a> }
          @if (c()?.email) { <a [href]="'mailto:' + c()?.email"><app-icon name="mail" [size]="16" /> {{ c()?.email }}</a> }
          @if (company.whatsappLink()) { <a [href]="company.whatsappLink()" target="_blank" rel="noopener"><app-icon name="chat" [size]="16" /> WhatsApp</a> }
        </aside>
      </div>
    </div>`,
})
export class AboutPage {
  company = inject(CompanyStore);
  c = this.company.company;
  open = signal(0);
  constructor() {
    this.company.load();
  }
}

@Component({
  template: `
    <div class="pub-wrap narrow-page wide">
      <div class="card card-pad">
        <h1>Privacy notice</h1>
        <p style="white-space:pre-line">{{ company.company()?.privacy_notice || 'Our privacy notice will be published here.' }}</p>
        <h3>Your rights</h3>
        <p>Under the Kenya Data Protection Act, 2019 you may ask to access, correct or delete personal data we hold about you,
          or object to its processing, subject to legal retention requirements for tenancy and financial records.
          Contact us using the details on the About page.</p>
      </div>
    </div>`,
})
export class PrivacyPage {
  company = inject(CompanyStore);
  constructor() {
    this.company.load();
  }
}
