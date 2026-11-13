/** Reglas de la terminal: importes exactos y confirmaciones persistentes. */
export const KEY_PREFIX = 'folio:pos:v1:';
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function uuid(provider = globalThis.crypto) {
  if (provider?.randomUUID) return provider.randomUUID();
  if (!provider?.getRandomValues) throw new Error('Este navegador no permite generar una solicitud segura.');
  const bytes = provider.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(v => v.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export function integer(value, min, max, label = 'Valor') {
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`${label} fuera del rango permitido.`);
  return value;
}
export function decimalToInt(raw, maximum = 1000000000) {
  const text = String(raw).trim();
  if (!/^\d{1,8}(?:[.,]\d{1,2})?$/.test(text)) throw new Error('Escribe un valor sin separadores de miles y con hasta dos decimales.');
  const [whole, fraction = ''] = text.replace(',', '.').split('.');
  const value = Number(BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0')));
  return integer(value, 0, maximum, 'Importe');
}
export function decimalText(value) { return `${Math.trunc(value / 100)}.${String(value % 100).padStart(2, '0')}`; }
export function money(value) {
  integer(value, 0, Number.MAX_SAFE_INTEGER, 'Importe');
  const amount = BigInt(value);
  return '$ ' + new Intl.NumberFormat('es-CO').format(amount / 100n) + ',' + String(amount % 100n).padStart(2, '0');
}
export function totals(lines) {
  let subtotal = 0n, taxes = 0n;
  for (const line of lines) {
    integer(line.cantidad, 1, 9999, 'Cantidad');
    integer(line.precio_unitario_centavos, 0, 1000000000, 'Precio');
    integer(line.impuesto_bps, 0, 10000, 'Impuesto');
    const base = BigInt(line.cantidad) * BigInt(line.precio_unitario_centavos);
    subtotal += base;
    taxes += (base * BigInt(line.impuesto_bps) + 5000n) / 10000n;
  }
  const total = subtotal + taxes;
  if (total > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('El total supera el rango de la terminal.');
  return { subtotal: Number(subtotal), taxes: Number(taxes), total: Number(total) };
}
export function dayInBogota(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date).map(p => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
export function nextDay(day) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) throw new Error('Fecha no válida.');
  const date = new Date(day + 'T12:00:00Z');
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== day) throw new Error('Fecha no válida.');
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}
export function emptyDraft(box) { return { v: 1, box, revision: null, operator: '', customer: 'GENERAL', lines: [], pending: null, lastReceipt: null }; }
export function intent(draft, requestId = uuid()) {
  if (!uuidPattern.test(requestId)) throw new Error('Solicitud no válida.');
  if (!draft.operator.trim() || draft.operator.trim().length > 120 || /[\x00-\x1f]/.test(draft.operator)) throw new Error('Escribe el nombre del operador.');
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(draft.box)) throw new Error('Selecciona una caja válida.');
  if (!/^(GENERAL|(?:CC|CE|NIT|PASAPORTE|OTRO)#[A-Z0-9-]{1,32})$/.test(draft.customer)) throw new Error('Selecciona un cliente válido.');
  if (!draft.lines.length || draft.lines.length > 50) throw new Error('Agrega entre 1 y 50 productos.');
  const ids = new Set();
  const lines = draft.lines.map(p => {
    if (!uuidPattern.test(p.producto_id) || ids.has(p.producto_id)) throw new Error('El carrito contiene productos repetidos o no válidos.');
    if (p.activo !== true) throw new Error('Retira los productos que ya no están disponibles.');
    ids.add(p.producto_id);
    return { producto_id: p.producto_id, cantidad: integer(p.cantidad, 1, 9999, 'Cantidad'), version_esperada: integer(p.version, 1, 2147483647, 'Versión') };
  });
  return { solicitud_id: requestId, caja_id: draft.box, operador_declarado: draft.operator.trim(), cliente_id: draft.customer, lineas: lines };
}
export function prepare(draft, requestId) {
  if (draft.pending) return structuredClone(draft);
  const body = intent(draft, requestId);
  return { ...structuredClone(draft), pending: { body, serialized: JSON.stringify(body), created: new Date().toISOString(), uncertain: false, rejection: null } };
}
export function failed(draft, error) {
  const next = structuredClone(draft);
  if (!next.pending) throw new Error('No hay confirmación pendiente.');
  const code = error.body?.codigo;
  const safeConflict = error.status === 409 && ['CATALOGO_CAMBIO', 'DATOS_CAMBIARON', 'CAJA_INACTIVA'].includes(code);
  const firstDefinitive = !next.pending.uncertain && [400, 404, 413].includes(error.status) && typeof error.body?.error === 'string';
  next.pending.rejection = safeConflict || firstDefinitive ? { message: error.message, body: error.body } : null;
  if (!next.pending.rejection) next.pending.uncertain = true;
  return next;
}
export function review(draft) {
  if (!draft.pending?.rejection) throw new Error('Conserva esta solicitud y vuelve a intentar su confirmación.');
  const changes = draft.pending.rejection.body?.carrito_actualizado || [];
  const lines = draft.lines.map(line => {
    const update = changes.find(p => p.producto_id === line.producto_id);
    return update ? { ...line, ...update, cantidad: line.cantidad } : { ...line };
  });
  return { ...structuredClone(draft), lines, pending: null };
}
export function validateInvoice(invoice) {
  if (!invoice || !uuidPattern.test(invoice.factura_id) || !uuidPattern.test(invoice.solicitud_id) || invoice.moneda !== 'COP' || typeof invoice.referencia !== 'string' || !invoice.referencia || !Number.isFinite(Date.parse(invoice.fecha_utc)) || typeof invoice.cliente?.nombre !== 'string' || typeof invoice.cliente?.tipo_documento !== 'string' || typeof invoice.operador_declarado !== 'string' || !Array.isArray(invoice.lineas) || !invoice.lineas.length || invoice.lineas.length > 50) throw new Error('El comprobante recibido está incompleto. Conserva la solicitud.');
  const ids = new Set(); let subtotal = 0, taxes = 0;
  for (const line of invoice.lineas) {
    if (!uuidPattern.test(line.producto_id) || ids.has(line.producto_id) || typeof line.nombre !== 'string') throw new Error('El comprobante contiene líneas no válidas.');
    ids.add(line.producto_id); integer(line.version,1,2147483647,'Versión');
    const calculated = totals([line]);
    if (line.base_centavos !== calculated.subtotal || line.impuesto_centavos !== calculated.taxes || line.total_centavos !== calculated.total) throw new Error('Los importes del comprobante no son coherentes.');
    subtotal += calculated.subtotal; taxes += calculated.taxes;
  }
  if (invoice.subtotal_centavos !== subtotal || invoice.impuestos_centavos !== taxes || invoice.total_centavos !== subtotal + taxes) throw new Error('Los totales del comprobante no son coherentes.');
  integer(invoice.total_centavos,0,Number.MAX_SAFE_INTEGER,'Total');
  return invoice;
}
export function confirmed(draft, result) {
  const body = draft.pending?.body, invoice = result?.factura;
  if (!body || !invoice || !uuidPattern.test(invoice.factura_id) || invoice.solicitud_id !== body.solicitud_id || invoice.caja_id !== body.caja_id || invoice.cliente_id !== body.cliente_id) throw new Error('La respuesta no permite confirmar esta venta. Conserva la solicitud y reintenta.');
  validateInvoice(invoice);
  if (invoice.operador_declarado !== body.operador_declarado) throw new Error('El comprobante no corresponde al operador.');
  const expected = new Map(body.lineas.map(l => [l.producto_id, l]));
  const seen = new Set();
  if (!Array.isArray(invoice.lineas) || invoice.lineas.length !== expected.size) throw new Error('El comprobante no corresponde al carrito.');
  for (const line of invoice.lineas) {
    const original = expected.get(line.producto_id);
    if (!original || seen.has(line.producto_id) || line.cantidad !== original.cantidad || line.version !== original.version_esperada) throw new Error('El comprobante no corresponde al carrito.');
    seen.add(line.producto_id);
  }
  return { ...structuredClone(draft), lines: [], pending: null, lastReceipt: invoice };
}
export class BoxStore {
  constructor(storage, makeId = uuid) { this.storage = storage; this.makeId = makeId; }
  key(box) { return KEY_PREFIX + box; }
  read(box) {
    try {
      const raw = this.storage.getItem(this.key(box));
      if (raw === null) return emptyDraft(box);
      const value = JSON.parse(raw);
      if (value.v !== 1 || value.box !== box || !Array.isArray(value.lines) || value.lines.length > 50 || typeof value.operator !== 'string' || typeof value.customer !== 'string') throw new Error();
      if (!uuidPattern.test(value.revision)) throw new Error();
      const ids = new Set();
      for (const line of value.lines) {
        if (!uuidPattern.test(line.producto_id) || ids.has(line.producto_id) || typeof line.nombre !== 'string' || typeof line.activo !== 'boolean') throw new Error();
        ids.add(line.producto_id); integer(line.version,1,2147483647); totals([line]);
      }
      if (value.pending && (!value.pending.body || value.pending.serialized !== JSON.stringify(value.pending.body) || value.pending.body.caja_id !== box || !uuidPattern.test(value.pending.body.solicitud_id))) throw new Error();
      if (value.pending && JSON.stringify(intent({...value, lines:value.lines.map(l=>({...l,activo:true}))},value.pending.body.solicitud_id)) !== value.pending.serialized) throw new Error();
      if (value.lastReceipt) validateInvoice(value.lastReceipt);
      return value;
    } catch { throw new Error('No pudimos recuperar el estado de esta caja. Conserva el almacenamiento del navegador y revisa el diagnóstico antes de volver a vender.'); }
  }
  save(draft) {
    const current = this.read(draft.box);
    if (current.revision !== draft.revision) throw new Error('Esta caja cambió en otra pestaña. Recarga su estado antes de continuar.');
    const value = { ...structuredClone(draft), revision: this.makeId() };
    try { this.storage.setItem(this.key(draft.box), JSON.stringify(value)); }
    catch { throw new Error('No se pudo guardar la solicitud en este navegador. Libera almacenamiento o habilítalo antes de confirmar.'); }
    return value;
  }
}
