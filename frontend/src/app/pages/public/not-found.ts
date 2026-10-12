import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Empty } from '../../shared/ui';

@Component({
  imports: [RouterLink, Empty],
  template: `
    <div style="padding:80px 16px">
      <app-empty icon="search" title="Page not found" text="The page you are looking for does not exist or has moved.">
        <a class="btn btn-primary" routerLink="/">Go to homepage</a>
      </app-empty>
    </div>`,
})
export class NotFoundPage {}
