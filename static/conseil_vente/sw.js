/**
 * Service Worker — JD Conseil Vente
 * Stratégie : Cache First pour les assets statiques,
 *             Network First pour les API Django.
 */

const CACHE_NAME     = 'jd-conseil-v1';
const CACHE_API_NAME = 'jd-api-v1';

// Assets à précacher au moment de l'installation
const ASSETS_STATIQUES = [
  '/',
  '/static/conseil_vente/manifest.json',
  'https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;1,300;1,400&family=DM+Sans:wght@300;400;500&display=swap',
];

// ── Installation ──────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(ASSETS_STATIQUES))
      .then(() => self.skipWaiting())
  );
});

// ── Activation — purge des anciens caches ─────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== CACHE_API_NAME)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Interception des requêtes ─────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Ne pas intercepter les requêtes non-GET (POST pour l'API conseil)
  if (request.method !== 'GET') return;

  // Requêtes API Django → Network First avec fallback cache
  if (url.pathname.startsWith('/api/') || url.pathname.includes('recommandations')) {
    event.respondWith(networkFirstAvecCache(request));
    return;
  }

  // Assets statiques & page principale → Cache First
  event.respondWith(cacheFirstAvecNetwork(request));
});

/**
 * Network First : essaie le réseau, met en cache la réponse,
 * et sert le cache si le réseau échoue.
 */
async function networkFirstAvecCache(request) {
  const cache = await caches.open(CACHE_API_NAME);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    // Réponse d'erreur JSON propre si rien en cache
    return new Response(
      JSON.stringify({ erreur: 'Hors ligne — données non disponibles', hors_ligne: true }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

/**
 * Cache First : sert depuis le cache si disponible,
 * sinon va chercher sur le réseau et met en cache.
 */
async function cacheFirstAvecNetwork(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    // Page de fallback hors-ligne si la page principale n'est pas en cache
    return new Response(
      '<h1 style="font-family:sans-serif;padding:40px">Hors ligne — Veuillez vous reconnecter au réseau local.</h1>',
      { status: 503, headers: { 'Content-Type': 'text/html' } }
    );
  }
}
