"""HTTP de comprobacion local con esperas acotadas para el arranque de Lambda."""
import json
import time
import urllib.error
import urllib.request


def request_json(url, *, method="GET", data=None, expected=(200,), attempts=3, timeout=35):
    """Reusar el mismo cuerpo en POST: solo usarlo para facturas idempotentes."""
    encoded = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"} if encoded is not None else {}
    last_error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=encoded, method=method, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status, payload, result_headers = response.status, json.load(response), dict(response.headers)
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read().decode("utf-8", errors="replace")
            finally:
                exc.close()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"error": raw[:300]}
            if status in expected:
                return status, payload, dict(exc.headers)
            last_error = RuntimeError(f"HTTP {status}: {payload}")
            if status not in {429, 500, 502, 503, 504}:
                raise last_error from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        else:
            if status not in expected:
                raise RuntimeError(f"HTTP {status} inesperado: {payload}")
            return status, payload, result_headers
        if attempt + 1 < attempts:
            print(f"Esperando respuesta de Lambda ({attempt + 1}/{attempts})...", flush=True)
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"No se obtuvo respuesta de {url}: {last_error}") from last_error
