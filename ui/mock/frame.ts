const ROUTE = /^[a-z/-]{0,40}$/;

/**
 * A stand-in for the Home Assistant frontend that shows the app in an ingress-style iframe:
 * HA's sidebar (collapsed below 870 px, as HA does) and toolbar around a same-origin frame.
 */
export function framePage(route: string): string {
  const safe = ROUTE.test(route) ? route : 'home';
  const items = ['Overview', 'Energy', 'Map', 'Logbook', 'History', 'ovenbird', 'Settings'];
  const list = items
    .map(
      (item) => `<li${item === 'ovenbird' ? ' class="on"' : ''}><i></i><span>${item}</span></li>`,
    )
    .join('');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="light dark" />
<title>Home Assistant (mock ingress)</title>
<style>
  :root { --ha-bg: #fafafa; --ha-side: #ffffff; --ha-line: #e0e0e0; --ha-text: #212121; --ha-bar: #03a9f4; }
  @media (prefers-color-scheme: dark) {
    :root { --ha-bg: #111111; --ha-side: #1c1c1c; --ha-line: #2c2c2c; --ha-text: #e1e1e1; --ha-bar: #1c1c1c; }
  }
  html, body { margin: 0; height: 100%; }
  body { display: flex; background: var(--ha-bg); color: var(--ha-text); font: 14px system-ui, sans-serif; }
  aside { width: 256px; flex: none; background: var(--ha-side); border-right: 1px solid var(--ha-line); }
  aside h1 { margin: 0; height: 56px; display: flex; align-items: center; padding: 0 16px; font-size: 20px; font-weight: 400; border-bottom: 1px solid var(--ha-line); }
  aside ul { list-style: none; margin: 8px 0; padding: 0; }
  aside li { display: flex; align-items: center; gap: 24px; height: 40px; margin: 4px 8px; padding: 0 8px; border-radius: 4px; }
  aside li.on { background: rgb(3 169 244 / 0.15); color: #03a9f4; }
  aside i { width: 24px; height: 24px; border-radius: 6px; background: currentColor; opacity: 0.5; }
  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  header { height: 56px; flex: none; display: flex; align-items: center; padding: 0 16px; background: var(--ha-bar); color: #fff; font-size: 20px; }
  iframe { flex: 1; width: 100%; border: 0; display: block; }
  @media (max-width: 870px) {
    aside { width: 56px; }
    aside h1, aside span { display: none; }
  }
  @media (max-width: 600px) {
    aside { display: none; }
  }
</style>
</head>
<body>
  <aside><h1>Home Assistant</h1><ul>${list}</ul></aside>
  <div class="main">
    <header>ovenbird</header>
    <iframe src="./#/${safe}" title="ovenbird" data-testid="ingress-frame"></iframe>
  </div>
</body>
</html>`;
}
