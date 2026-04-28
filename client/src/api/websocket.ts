/**
 * Shared WebSocket connection URL.
 *
 * Same-origin via the page's host — nginx (prod) or Vite dev server (local)
 * forwards /ws upstream to the FastAPI backend. Works in three setups:
 *
 *   - Production behind nginx — server block has a `location /ws { ... }`
 *     reverse-proxy block to 127.0.0.1:6002, including the standard
 *     Upgrade/Connection headers.
 *   - `npm run dev` (Vite) — vite.config.ts proxies /ws to localhost:6002.
 *   - `npx serve -s dist -l 6001` — bare static server, no proxy: the WS
 *     upgrade will fail. Use `npm run dev` for local dev instead.
 */
export const WS_URL = `${
  window.location.protocol === 'https:' ? 'wss:' : 'ws:'
}//${window.location.host}/ws`
