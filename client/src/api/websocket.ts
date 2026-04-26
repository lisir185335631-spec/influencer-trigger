/**
 * Shared WebSocket connection URL.
 *
 * Direct-connect to backend WS port. The frontend is served by
 * `npx serve -s dist -l 6001` which is a static file server with NO proxy —
 * so `${window.location.host}` (= 6001) would land on `serve` and fail the
 * WebSocket upgrade. Hardcoding 6002 (backend port) works for both
 * `npm run dev` (Vite proxy is then bypassed but harmless) and the
 * `serve` setup.
 *
 * For nginx-reverse-proxied production, replace with
 * `${window.location.host}` (the proxy then forwards /ws upstream).
 */
export const WS_URL = `${
  window.location.protocol === 'https:' ? 'wss:' : 'ws:'
}//${window.location.hostname}:6002/ws`
