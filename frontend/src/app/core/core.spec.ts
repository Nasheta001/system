import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';
import { ListState } from '../shared/list';
import { Api, parseError } from './api.service';
import { Auth } from './auth.service';
import { LabelPipe, formatKes } from './format';
import { capGuard, staffGuard, tenantGuard } from './guards';
import { Ui } from './ui.service';

describe('parseError', () => {
  it('extracts detail messages', () => {
    const e = new HttpErrorResponse({ status: 400, error: { detail: 'Invalid email or password.' } });
    expect(parseError(e).message).toBe('Invalid email or password.');
  });

  it('maps field errors', () => {
    const e = new HttpErrorResponse({ status: 400, error: { email: ['Enter a valid email.'], phone: ['Required.'] } });
    const r = parseError(e);
    expect(r.fields['email']).toBe('Enter a valid email.');
    expect(r.message).toBe('Please correct the highlighted fields.');
  });

  it('explains network failures', () => {
    expect(parseError(new HttpErrorResponse({ status: 0 })).message).toContain('Cannot reach the server');
  });
});

describe('formatting', () => {
  it('formats Kenyan shillings', () => {
    expect(formatKes('45000')).toBe('KES 45,000');
    expect(formatKes(-1500.5)).toBe('−KES 1,500.5');
    expect(formatKes(null)).toBe('—');
  });

  it('labels statuses', () => {
    const p = new LabelPipe();
    expect(p.transform('under_review')).toBe('Under review');
    expect(p.transform('logged')).toBe('Logged only');
    expect(p.transform('something_new')).toBe('Something new');
  });
});

describe('Ui service', () => {
  it('resolves confirmations with the typed reason', async () => {
    const ui = new Ui();
    const pending = ui.confirm({ title: 'Void', message: 'x', reasonLabel: 'Reason' });
    expect(ui.confirmRequest()?.title).toBe('Void');
    ui.answer('Duplicate entry');
    expect(await pending).toBe('Duplicate entry');
    expect(ui.confirmRequest()).toBeNull();
  });
});

describe('route guards', () => {
  let http: HttpTestingController;
  let router: Router;
  const state = { url: '/management/payments' } as RouterStateSnapshot;

  function setup() {
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  }

  async function runGuard(guard: any, me: any, route = new ActivatedRouteSnapshot()) {
    const result = TestBed.runInInjectionContext(() => guard(route, state)) as Promise<boolean | UrlTree>;
    await Promise.resolve();
    const req = http.expectOne('/api/auth/me/');
    if (me) req.flush(me);
    else req.flush({ detail: 'no' }, { status: 401, statusText: 'Unauthorized' });
    return result;
  }

  beforeEach(setup);

  it('sends anonymous users to the management login with a return url', async () => {
    const r = (await runGuard(staffGuard, null)) as UrlTree;
    expect(router.serializeUrl(r)).toBe('/management/login?next=%2Fmanagement%2Fpayments');
  });

  it('keeps tenants out of the management area', async () => {
    const r = (await runGuard(staffGuard, { role: 'tenant', capabilities: [] })) as UrlTree;
    expect(router.serializeUrl(r)).toBe('/tenant/dashboard');
  });

  it('keeps staff out of the tenant portal', async () => {
    const r = (await runGuard(tenantGuard, { role: 'manager', capabilities: [] })) as UrlTree;
    expect(router.serializeUrl(r)).toBe('/management/dashboard');
  });

  it('checks capabilities for restricted pages', async () => {
    const route = new ActivatedRouteSnapshot();
    (route as any).data = { cap: 'view_payments' };
    const r = (await runGuard(capGuard, { role: 'caretaker', capabilities: ['view_maintenance'] }, route)) as UrlTree;
    expect(router.serializeUrl(r)).toBe('/management/dashboard');
    expect(TestBed.inject(Auth).can('view_maintenance')).toBe(true);
  });
});

describe('ListState', () => {
  it('requests the right page with filters and stores results', async () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const http = TestBed.inject(HttpTestingController);
    const list = new ListState(TestBed.inject(Api), 'payments/', { status: 'pending', property: '' });
    list.page.set(2);
    const done = list.load();
    const req = http.expectOne((r) => r.url === '/api/payments/');
    expect(req.request.params.get('status')).toBe('pending');
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.has('property')).toBe(false); // empty filters are not sent
    req.flush({ count: 30, next: null, previous: null, results: [{ id: 1 }] });
    await done;
    expect(list.items().length).toBe(1);
    expect(list.count()).toBe(30);
  });
});
