import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { AcceptInvitePage } from './access';

describe('AcceptInvitePage', () => {
  function setup(fragment: string | null) {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]), provideHttpClient(), provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { fragment } } },
      ],
    });
    const fixture = TestBed.createComponent(AcceptInvitePage);
    return { page: fixture.componentInstance, http: TestBed.inject(HttpTestingController) };
  }

  it('sends the fragment token in the request body, never in the URL', async () => {
    const { page, http } = setup('token=abc123');
    const req = http.expectOne('/api/auth/invitations/check/');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ token: 'abc123' });
    expect(req.request.urlWithParams).not.toContain('abc123');
    req.flush({ kind: 'tenant', email: 't@x.test', company: 'Demo', expires_at: new Date().toISOString() });
    await Promise.resolve();
    await Promise.resolve();
    expect(page.state()).toBe('ready');
  });

  it('shows an error without calling the API when the token is missing', () => {
    const { page, http } = setup(null);
    http.expectNone('/api/auth/invitations/check/');
    expect(page.state()).toBe('invalid');
  });

  it('reports invalid or used invitations', async () => {
    const { page, http } = setup('token=used');
    http.expectOne('/api/auth/invitations/check/').flush(
      { detail: 'This invitation link is invalid, has expired or has already been used.' }, { status: 400, statusText: 'Bad Request' });
    await Promise.resolve();
    await Promise.resolve();
    expect(page.state()).toBe('invalid');
    expect(page.error()).toContain('already been used');
  });
});
