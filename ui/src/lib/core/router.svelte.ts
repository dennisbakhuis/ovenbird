import { buildHash, isNewPage, parseLocation, type Location, type Route } from './location';

export { buildHash, isNewPage, parseLocation, parseRoute, ROUTES } from './location';
export type { Location, Route } from './location';

class Router {
  location = $state<Location>(parseLocation(typeof window === 'undefined' ? '' : location.hash));

  get route(): Route {
    return this.location.route;
  }

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('hashchange', () => {
        const previous = this.location;
        this.location = parseLocation(window.location.hash);
        if (isNewPage(previous, this.location)) window.scrollTo({ top: 0, left: 0 });
      });
    }
  }

  navigate(route: Route, sub: string[] = [], query: Record<string, string | undefined> = {}): void {
    window.location.hash = buildHash(route, sub, query);
  }
}

export const router = new Router();
