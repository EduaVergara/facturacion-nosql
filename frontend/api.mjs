export class ApiFailure extends Error {
  constructor(status, body) { super(body?.error || 'No se pudo obtener una respuesta del servidor.'); this.status = status; this.body = body; }
}
export class Api {
  constructor({ fetcher = globalThis.fetch.bind(globalThis), onRequest = () => {}, timeout = 45000 } = {}) { this.fetcher = fetcher; this.onRequest = onRequest; this.timeout = timeout; }
  async request(path, { method = 'GET', body, serialized, allow = [] } = {}) {
    if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Ruta de API no válida.');
    const started = performance.now(), controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let status = 0, source = '', cache = '', data = null;
    try {
      const raw = serialized ?? (body === undefined ? undefined : JSON.stringify(body));
      const response = await this.fetcher('/api' + path, { method, body: raw, headers: raw === undefined ? {} : { 'Content-Type': 'application/json' }, signal: controller.signal, cache: 'no-store' });
      status = response.status;
      source = response.headers.get('X-Data-Source') || '';
      cache = response.headers.get('X-Cache') || '';
      try { data = await response.json(); } catch { throw new ApiFailure(0, { error: 'La respuesta no se pudo interpretar. Conserva la solicitud para reintentar.' }); }
      if (!response.ok && !allow.includes(status)) throw new ApiFailure(status, data);
      return data;
    } catch (error) {
      if (error instanceof ApiFailure) throw error;
      throw new ApiFailure(0, { error: 'No recibimos confirmación del servidor. Comprueba la conexión y reintenta la misma solicitud.' });
    } finally {
      clearTimeout(timer);
      try { this.onRequest({ time: new Date().toISOString(), method, path, status, source, cache, elapsed: Math.round(performance.now() - started), data }); } catch { /* El diagnóstico no altera el resultado de la venta. */ }
    }
  }
}
