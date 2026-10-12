import { provideHttpClient, withInterceptors, withXsrfConfiguration } from '@angular/common/http';
import {
  ApplicationConfig, inject, provideAppInitializer, provideBrowserGlobalErrorListeners, provideZonelessChangeDetection,
} from '@angular/core';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling, withNavigationErrorHandler } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { routes } from './app.routes';
import { Api } from './core/api.service';
import { authInterceptor } from './core/interceptor';

/** After a deployment an open tab may ask for a lazy chunk that no longer exists.
 *  Load the new build once instead of leaving a blank page (guarded against loops). */
function reloadOnStaleChunk(error: { error: unknown; url: string }) {
  const msg = String((error.error as Error)?.message ?? error.error);
  if (!/dynamically imported module|Importing a module script failed|error loading dynamically/i.test(msg)) return;
  try {
    if (sessionStorage.getItem('chunk-reload') === error.url) return;
    sessionStorage.setItem('chunk-reload', error.url);
  } catch {
    /* storage unavailable: still reload once */
  }
  location.assign(error.url);
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes, withComponentInputBinding(), withInMemoryScrolling({ scrollPositionRestoration: 'top' }),
      withNavigationErrorHandler(reloadOnStaleChunk)),
    // Django sets the XSRF-TOKEN cookie; Angular echoes it in X-XSRF-TOKEN on unsafe requests.
    provideHttpClient(
      withXsrfConfiguration({ cookieName: 'XSRF-TOKEN', headerName: 'X-XSRF-TOKEN' }),
      withInterceptors([authInterceptor]),
    ),
    provideAppInitializer(() => firstValueFrom(inject(Api).get('auth/csrf/')).catch(() => null)),
  ],
};
