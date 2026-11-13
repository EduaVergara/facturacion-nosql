import { Api, ApiFailure } from './api.mjs';
import { BoxStore, KEY_PREFIX, emptyDraft, prepare, failed, review, confirmed, validateInvoice, totals, money, decimalText, decimalToInt, dayInBogota, nextDay } from './domain.mjs';

const $ = id => document.getElementById(id);
const paths = {
  bag:'M5 7h14l1 13H4L5 7Zm3 0V5a4 4 0 0 1 8 0v2', grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 4a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.9M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  clock:'M12 8v5l3 2M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0Z', activity:'M2 12h4l3-8 6 16 3-8h4',
  receipt:'M6 3h12v18l-3-2-3 2-3-2-3 2V3ZM9 7h6M9 11h6M9 15h4', refresh:'M20 7v5h-5M4 17v-5h5M5 7a8 8 0 0 1 13-2l2 2M4 17l2 2a8 8 0 0 0 13-2',
  search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', monitor:'M3 3h18v13H3zM12 16v5M8 21h8', check:'m5 12 4 4L19 6', printer:'M6 9V3h12v6M6 18H3v-8h18v8h-3M6 14h12v7H6z', empty:'M3 6h3l2 12h10l3-9H7M10 21h.01M18 21h.01'
};
function icon(name) { const span = document.createElement('span'); span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.receipt}"/></svg>`; return span; }
document.querySelectorAll('[data-icon]').forEach(node => node.replaceChildren(icon(node.dataset.icon)));
function el(tag, text = '', cls = '') { const node = document.createElement(tag); if (text !== null) node.textContent = text; if (cls) node.className = cls; return node; }
function button(text, callback, cls = 'text-button') { const node = el('button', text, cls); node.type = 'button'; node.addEventListener('click', callback); return node; }
function cell(content) { const node = el('td'); if (content instanceof Node) node.append(content); else node.textContent = content; return node; }
function notice(message, error = false) { $('notice').textContent = message; $('notice').className = 'notice' + (error ? ' error' : ''); $('notice').hidden = !message; }
function report(error) { notice(error.message || String(error), true); }
function empty(message, description = '', wide = false) { const node = el('div', null, 'empty-state' + (wide ? ' empty-wide' : '')); node.append(icon('empty'), el('strong', message), el('p', description)); return node; }
function shortId(id) { return 'DEMO-' + id.slice(0,8).toUpperCase(); }
function dateText(value) { return new Intl.DateTimeFormat('es-CO', { timeZone:'America/Bogota', dateStyle:'medium', timeStyle:'short' }).format(new Date(value)); }

const state = { products:[], productCursor:null, clients:[], clientCursor:null, boxes:[], draft:emptyDraft('c01'), view:'venta', busy:false, adding:new Set(), foreign:false, blocked:false, health:null, logs:[], editor:null, history:{ rows:[], cursor:null, query:null, path:null, epoch:0, busy:false } };
let store;
const api = new Api({ onRequest: record => { state.logs.unshift(record); state.logs.length = Math.min(state.logs.length,40); renderLogs(); } });
try { store = new BoxStore(window.localStorage); } catch { state.blocked = true; }

function commit(next) {
  if (state.blocked || state.foreign || !store) throw new Error('Recupera el estado guardado de esta caja antes de confirmar otra venta.');
  state.draft = store.save(next); renderCart();
}
function loadBox(box) {
  state.foreign = false; state.blocked = false;
  try { if (!store) throw new Error('El navegador tiene deshabilitado el almacenamiento.'); state.draft = store.read(box); }
  catch (error) { state.draft = emptyDraft(box); state.blocked = true; report(error); }
  const url = new URL(location.href); url.searchParams.set('caja',box); history.replaceState(null,'',url);
  $('box').value = box; renderCart(); renderProducts();
  if (state.draft.pending) notice('Esta caja tiene una confirmación pendiente. Reintenta la misma solicitud para conocer su resultado.',true);
}
function isLocked() { return state.busy || !!state.draft.pending || state.blocked || state.foreign; }
function customerOptions() {
  const values = [...state.clients];
  if (!values.some(c => c.cliente_id === 'GENERAL')) values.unshift({cliente_id:'GENERAL', nombre:'Cliente general'});
  if (!values.some(c => c.cliente_id === state.draft.customer)) values.unshift({cliente_id:state.draft.customer,nombre:state.draft.customer});
  return values;
}
function renderCustomers() {
  const current = state.draft.customer;
  $('customer').replaceChildren(...customerOptions().map(c => { const node = el('option', c.nombre + (c.cliente_id === 'GENERAL' ? '' : ' · ' + c.cliente_id)); node.value = c.cliente_id; return node; }));
  $('customer').value = current;
  $('client-options').replaceChildren(...state.clients.map(c => { const option = el('option'); option.value = c.cliente_id; option.label = c.nombre; return option; }));
  const search = $('client-search').value.toLocaleLowerCase('es');
  const rows = state.clients.filter(c => `${c.nombre} ${c.cliente_id}`.toLocaleLowerCase('es').includes(search));
  $('client-table').replaceChildren(...rows.map(c => { const row = el('tr'); row.append(cell(el('strong',c.nombre)),cell(c.tipo_documento || c.cliente_id.split('#')[0]),cell(c.numero_documento ?? c.cliente_id.split('#').slice(1).join('#')),cell(button('Editar nombre',() => openClient(c.cliente_id)))); return row; }));
  if (!rows.length) tableEmpty('client-table','No hay clientes que coincidan.');
  $('more-clients').hidden = $('more-sale-clients').hidden = !state.clientCursor;
}
function tableEmpty(id, message) { const row = el('tr'), col = cell(message); col.colSpan = 8; row.append(col); $(id).replaceChildren(row); }
function renderProducts() {
  const search = $('product-search').value.trim().toLocaleLowerCase('es');
  const matches = state.products.filter(p => p.nombre.toLocaleLowerCase('es').includes(search));
  $('product-count').textContent = state.products.length;
  $('loaded-caption').textContent = `${state.products.length} productos cargados`;
  $('product-grid').replaceChildren(...matches.map((p,index) => {
    const card = el('button',null,'product-card'); card.type='button'; card.disabled = isLocked() || p.activo === false || state.adding.has(p.producto_id);
    card.setAttribute('aria-label',`Agregar ${p.nombre}, ${money(p.precio_unitario_centavos)}`);
    const top=el('div',null,'product-top'); top.append(el('span',p.nombre.slice(0,1).toUpperCase(),'product-symbol tone-'+index%4),el('span',p.activo ? `${decimalText(p.impuesto_bps)} % imp.` : 'No disponible','tax-pill'));
    const price=el('div',money(p.precio_unitario_centavos),'product-price'); price.append(el('small','por unidad'));
    card.append(top,el('h3',p.nombre),price,el('span',state.adding.has(p.producto_id) ? '…' : '+','add-product'));
    card.addEventListener('click',() => addProduct(p.producto_id)); return card;
  }));
  if (!matches.length) $('product-grid').append(empty(state.products.length ? 'No encontramos ese producto' : 'Tu catálogo está listo para crecer',state.products.length ? 'Prueba otro nombre o carga más productos.' : 'Crea un producto desde la sección Productos.',true));
  const adminSearch=$('admin-product-search').value.toLocaleLowerCase('es');
  const admin=state.products.filter(p => p.nombre.toLocaleLowerCase('es').includes(adminSearch));
  $('product-table').replaceChildren(...admin.map(p => { const row=el('tr'); row.append(cell(el('strong',p.nombre)),cell(money(p.precio_unitario_centavos)),cell(decimalText(p.impuesto_bps)+' %'),cell(el('span',p.activo ? 'Disponible' : 'Inactivo','badge'+(p.activo ? '' : ' off'))),cell(button('Editar',() => openProduct(p.producto_id)))); return row; }));
  if (!admin.length) tableEmpty('product-table','No hay productos que coincidan.');
  $('load-products').hidden = $('admin-more-products').hidden = !state.productCursor;
}
function renderCart() {
  const draft=state.draft, locked=isLocked();
  if (document.activeElement !== $('operator')) $('operator').value=draft.operator;
  $('operator').disabled=$('customer').disabled=$('quick-client').disabled=locked;
  $('box').disabled=state.busy || !!draft.pending || !!draft.lines.length || !!state.adding.size;
  renderCustomers();
  $('last-receipt').disabled=!draft.lastReceipt;
  $('cart-count').textContent=draft.lines.reduce((sum,l) => sum+l.cantidad,0);
  $('cart-lines').replaceChildren(...draft.lines.map(line => {
    const row=el('div',null,'cart-line'), desc=el('div'); desc.append(el('h3',line.nombre),el('p',line.activo ? `${money(line.precio_unitario_centavos)} / unidad · ${decimalText(line.impuesto_bps)} % imp.` : 'Ya no disponible: retíralo del carrito',line.activo ? 'muted' : 'muted error-line'));
    row.append(desc,el('strong',money(totals([line]).total)));
    const controls=el('div',null,'line-controls'), quantity=el('div',null,'quantity');
    const minus=button('−',() => changeQuantity(line.producto_id,line.cantidad-1),''), plus=button('+',() => changeQuantity(line.producto_id,line.cantidad+1),'');
    minus.setAttribute('aria-label','Reducir cantidad de '+line.nombre); plus.setAttribute('aria-label','Aumentar cantidad de '+line.nombre);
    const input=el('input'); input.type='number'; input.min='1'; input.max='9999'; input.value=line.cantidad; input.setAttribute('aria-label','Cantidad de '+line.nombre);
    input.addEventListener('change',() => changeQuantity(line.producto_id,Number(input.value)));
    minus.disabled=plus.disabled=input.disabled=locked;
    quantity.append(minus,input,plus); const remove=button('Retirar',() => removeLine(line.producto_id),'remove-line'); remove.disabled=locked;
    controls.append(quantity,remove); row.append(controls); return row;
  }));
  if (!draft.lines.length) $('cart-lines').append(empty('Tu próxima venta empieza aquí','Agrega productos del catálogo para armar el carrito.'));
  try { const calculated=totals(draft.lines); $('subtotal').textContent=money(calculated.subtotal); $('taxes').textContent=money(calculated.taxes); $('total').textContent=money(calculated.total); }
  catch(error) { state.blocked=true; report(error); }
  $('pending').hidden=!draft.pending;
  if (draft.pending) {
    const pending=draft.pending;
    $('pending').replaceChildren(el('strong',pending.rejection ? 'Revisa la venta antes de continuar' : 'Confirmación pendiente'),el('p',pending.rejection?.message || 'Conservamos el carrito y la solicitud. El reintento consulta o confirma esta misma venta.'),el('small','Solicitud: '+pending.body.solicitud_id));
  }
  $('review-sale').hidden=!draft.pending?.rejection;
  $('review-sale').disabled=state.busy || state.foreign || state.blocked;
  $('confirm-label').textContent=state.busy ? 'Confirmando…' : draft.pending ? 'Reintentar confirmación' : 'Confirmar venta';
  $('confirm-sale').disabled=state.busy || state.blocked || state.foreign || !!state.adding.size || !!draft.pending?.rejection || (!draft.pending && (!draft.lines.length || !draft.operator.trim() || draft.lines.some(l => !l.activo) || !state.boxes.some(b => b.caja_id===draft.box && b.activo)));
  $('clear-cart').disabled=locked || !draft.lines.length || !!state.adding.size;
}
async function loadProducts(more=false) {
  try { const query=new URLSearchParams({limit:'25'}); if(more&&state.productCursor) query.set('cursor',state.productCursor); const data=await api.request('/productos?'+query); state.products=merge(more?state.products:[],data.items,'producto_id'); state.productCursor=data.next_cursor; renderProducts(); }
  catch(error){ report(error); }
}
async function loadClients(more=false) {
  try { const query=new URLSearchParams({limit:'25'}); if(more&&state.clientCursor) query.set('cursor',state.clientCursor); const data=await api.request('/clientes?'+query); state.clients=merge(more?state.clients:[],data.items,'cliente_id'); state.clientCursor=data.next_cursor; renderCustomers(); }
  catch(error){ report(error); }
}
function merge(a,b,key) { return [...new Map([...a,...b].map(item => [item[key],item])).values()]; }
async function addProduct(identifier) {
  if(isLocked()||state.adding.has(identifier)) return;
  state.adding.add(identifier); renderProducts(); renderCart();
  try {
    const product=await api.request('/productos/'+encodeURIComponent(identifier));
    if(!product.activo) throw new Error('Ese producto ya no está disponible.');
    if(isLocked()) return;
    const next=structuredClone(state.draft), existing=next.lines.find(p => p.producto_id===identifier);
    if(existing) { if(existing.cantidad>=9999) throw new Error('La cantidad máxima por producto es 9999.'); Object.assign(existing,product,{cantidad:existing.cantidad+1}); }
    else { if(next.lines.length>=50) throw new Error('El carrito admite hasta 50 productos distintos.'); next.lines.push({...product,cantidad:1}); }
    commit(next); notice('');
  } catch(error){ report(error); }
  finally { state.adding.delete(identifier); renderProducts(); renderCart(); }
}
function changeQuantity(identifier,value) { if(isLocked()) return; try { if(!Number.isInteger(value)||value<1||value>9999) throw new Error('Usa una cantidad entera entre 1 y 9999.'); const next=structuredClone(state.draft); next.lines.find(l=>l.producto_id===identifier).cantidad=value; commit(next); } catch(error){ report(error); renderCart(); } }
function removeLine(identifier) { if(isLocked()) return; try { commit({...state.draft,lines:state.draft.lines.filter(l=>l.producto_id!==identifier)}); renderProducts(); } catch(error){ report(error); } }
async function confirmSale() {
  if(state.busy||state.blocked||state.foreign) return;
  try { if(!state.draft.pending) commit(prepare(state.draft)); }
  catch(error){ report(error); return; }
  state.busy=true; renderCart(); renderProducts();
  let accepted=null;
  try {
    const result=await api.request('/facturas',{method:'POST',serialized:state.draft.pending.serialized});
    accepted=confirmed(state.draft,result);
    try { commit(accepted); notice(result.replayed ? 'Recuperamos la factura original. No se creó otra venta.' : 'Venta confirmada y guardada en el servidor.'); }
    catch(error) { notice('El servidor confirmó la venta, pero no se pudo guardar el estado local. Conserva esta pestaña y reintenta la misma solicitud; se recuperará la factura original.',true); }
    showReceipt(result.factura);
  } catch(error) {
    try { if(!accepted) commit(failed(state.draft,error instanceof ApiFailure?error:new ApiFailure(0,{error:error.message}))); } catch(storageError){ report(storageError); }
    report(error);
  } finally { state.busy=false; renderCart(); renderProducts(); }
}
function reviewSale() { try { commit(review(state.draft)); notice('Carrito listo para revisar. Comprueba productos, cantidades y cliente antes de confirmar otra vez.'); renderProducts(); } catch(error){ report(error); } }
function showView(view) {
  if(!['venta','productos','clientes','historial','diagnostico'].includes(view)) view='venta'; state.view=view;
  document.querySelectorAll('.view').forEach(node=>node.hidden=node.id!=='view-'+view);
  document.querySelectorAll('[data-view]').forEach(node=>{ node.classList.toggle('active',node.dataset.view===view); if(node.dataset.view===view) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current'); });
  location.hash=view;
}
async function health() {
  $('connection').textContent='Comprobando servicios'; $('connection').className='status';
  try { state.health=await api.request('/health',{allow:[503]}); }
  catch(error){ state.health={estado:'sin conexión',dynamodb:{estado:'desconocido'},redis:{estado:'desconocido'},error:error.message}; }
  const ready=state.health.estado==='ok', degraded=state.health.estado==='degradado';
  const dot=el('i'); $('connection').replaceChildren(dot,document.createTextNode(ready?'Servicios listos':degraded?'Servicios degradados':'Sin conexión al servidor')); $('connection').className='status '+(ready?'ok':degraded?'degraded':'offline');
  const cards=[['API de facturación',state.health.estado,ready?'Lista para recibir operaciones':degraded?'Consultable; revisa los servicios':'No se pudo obtener respuesta'],['DynamoDB',state.health.dynamodb?.estado,state.health.dynamodb?.tabla||'Fuente central de las ventas'],['Redis',state.health.redis?.estado,'Caché de productos y facturas']];
  $('health-cards').replaceChildren(...cards.map(([name,status,note])=>{ const card=el('div',null,'health-card '+(status==='ok'?'':status==='error'?'danger':'warning')); card.append(el('span',name),el('strong',status==='ok'?'Operativo':status==='error'?'No disponible':status||'Desconocido'),el('p',note)); return card; }));
  $('health-json').textContent=JSON.stringify(state.health,null,2);
}
function renderLogs() {
  $('request-table').replaceChildren(...state.logs.map(r=>{ const row=el('tr'); row.append(cell(new Intl.DateTimeFormat('es-CO',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'America/Bogota'}).format(new Date(r.time))),cell(r.method+' '+r.path),cell(String(r.status||'Sin respuesta')),cell(r.source||'—'),cell(r.cache||'—'),cell(r.elapsed+' ms')); return row; }));
  if(!state.logs.length) tableEmpty('request-table','Las peticiones de esta terminal aparecerán aquí.');
}
function field(label,value,name,{type='text',required=true,readOnly=false,help='',maxLength}={}) {
  const container=el('label',label), input=el('input'); input.name=name; input.type=type; input.value=value; input.required=required; input.readOnly=readOnly; if(maxLength) input.maxLength=maxLength; if(type==='text'&&['price','tax'].includes(name)) input.inputMode='decimal'; container.append(input); if(help) container.append(el('span',help,'field-note')); return container;
}
function editorTitle(title,kind,record,quick=false) { state.editor={kind,record,quick}; $('editor-title').textContent=title; $('editor-error').hidden=true; $('editor-fields').replaceChildren(); $('editor-save').disabled=false; }
async function openProduct(identifier=null) {
  try {
    const record=identifier?await api.request('/productos/'+encodeURIComponent(identifier)):null;
    editorTitle(record?'Editar producto':'Crear producto','product',record);
    $('editor-fields').append(field('Nombre',record?.nombre||'','name',{maxLength:120}),field('Precio antes de impuesto · COP',record?decimalText(record.precio_unitario_centavos):'','price',{help:'Sin separadores de miles. Ejemplo: 5000.00'}),field('Impuesto · %',record?decimalText(record.impuesto_bps):'10.00','tax',{help:'Tasa de demostración configurable, de 0 a 100 %.'}));
    const label=el('label',null,'check-label'), active=el('input'); active.type='checkbox'; active.name='active'; active.checked=record?.activo??true; label.append(active,document.createTextNode('Disponible para la venta')); $('editor-fields').append(label); $('editor').showModal();
  } catch(error){ report(error); }
}
async function openClient(identifier=null,quick=false) {
  try {
    const record=identifier?await api.request('/clientes/'+encodeURIComponent(identifier)):null;
    editorTitle(record?'Editar nombre del cliente':'Crear cliente','client',record,quick);
    $('editor-fields').append(field('Nombre',record?.nombre||'','name',{maxLength:120}));
    const label=el('label','Tipo de identificación'), select=el('select'); select.name='documentType';
    for(const kind of record?.cliente_id==='GENERAL'?['GENERAL']:['CC','CE','NIT','PASAPORTE','OTRO']) { const option=el('option',kind); option.value=kind; select.append(option); } select.value=record?.tipo_documento||'CC'; select.disabled=!!record; label.append(select);
    $('editor-fields').append(label,field('Número de identificación',record?.numero_documento||'','documentNumber',{required:!record,readOnly:!!record,maxLength:32,help:record?'La identificación permanece igual; puedes actualizar el nombre.':'Conservamos los ceros iniciales. Usa letras, números o guion.'})); $('editor').showModal();
  } catch(error){ report(error); }
}
async function saveEditor(event) {
  event.preventDefault(); const {kind,record,quick}=state.editor, data=new FormData(event.target); $('editor-save').disabled=true; $('editor-error').hidden=true;
  try {
    const name=String(data.get('name')).trim(); let result;
    if(kind==='product') {
      const body={nombre:name,precio_unitario_centavos:decimalToInt(data.get('price')),impuesto_bps:decimalToInt(data.get('tax'),10000),activo:data.get('active')==='on'};
      if(record) body.version_esperada=record.version;
      result=await api.request(record?'/productos/'+encodeURIComponent(record.producto_id):'/productos',{method:record?'PUT':'POST',body});
      state.products=merge(state.products,[result],'producto_id'); renderProducts();
    } else {
      const body=record?{nombre:name,version_esperada:record.version}:{nombre:name,tipo_documento:String(data.get('documentType')),numero_documento:String(data.get('documentNumber')).trim().toUpperCase()};
      result=await api.request(record?'/clientes/'+encodeURIComponent(record.cliente_id):'/clientes',{method:record?'PUT':'POST',body});
      state.clients=merge(state.clients,[result],'cliente_id'); renderCustomers();
      if(quick&&!isLocked()) {
        try { commit({...state.draft,customer:result.cliente_id}); }
        catch(error) { $('editor').close(); report(new Error('El cliente fue creado. No se pudo seleccionarlo en esta caja: '+error.message)); return; }
      }
    }
    $('editor').close(); notice(record?'Cambios guardados. Las facturas anteriores conservan sus datos.':'Registro creado correctamente.');
  } catch(error){ $('editor-error').textContent=error.status===409?'El registro ya existe o cambió en otra terminal. Revisa sus datos actuales antes de volver a guardar.':error.message; $('editor-error').hidden=false; }
  finally { $('editor-save').disabled=false; }
}
function historyMode() {
  const mode=$('history-kind').value;
  for(const [id,show] of [['history-day-label',mode==='dia'],['history-client-label',mode==='cliente'],['history-box-label',mode==='caja'],['history-from-label',mode!=='dia'],['history-until-label',mode!=='dia']]) $(id).hidden=!show;
  $('history-day').required=mode==='dia'; $('history-client').required=mode==='cliente'; $('history-from').required=$('history-until').required=mode!=='dia';
  $('history-hint').textContent=mode==='dia'?'El día se interpreta en la hora de Colombia.':'Hasta no se incluye. Para ver el día 12, selecciona hasta el 13. Máximo 31 días.';
  resetHistory();
}
function resetHistory() { state.history.epoch++; state.history.rows=[]; state.history.cursor=null; state.history.query=null; state.history.path=null; state.history.busy=false; renderHistory(); }
function renderHistory() {
  $('history-count').textContent=state.history.rows.length;
  $('history-caption').textContent=state.history.query?(state.history.busy?'Consultando…':`${state.history.rows.length} facturas cargadas · más recientes primero`):'Aplica los filtros para consultar.';
  $('history-table').replaceChildren(...state.history.rows.map(item=>{ const row=el('tr'); row.append(cell(el('strong',shortId(item.factura_id))),cell(dateText(item.fecha_utc)),cell(item.cliente_id),cell(item.caja_id),cell(el('strong',money(item.total_centavos))),cell(button('Ver comprobante',()=>openReceipt(item.factura_id)))); return row; }));
  if(!state.history.rows.length) tableEmpty('history-table',state.history.busy?'Consultando facturas…':state.history.query?'No hay facturas para este filtro.':'Selecciona un filtro y consulta las ventas.');
  $('more-history').hidden=!state.history.cursor; $('more-history').disabled=state.history.busy;
}
async function loadHistory(more=false) {
  if(state.history.busy) return;
  let epoch=null;
  try {
    if(!more) {
      const mode=$('history-kind').value, query={limit:'25'}; let path='/facturas';
      if(mode==='dia') query.fecha=$('history-day').value;
      else { query.desde=$('history-from').value; query.hasta=$('history-until').value; if(!query.desde||!query.hasta||query.desde>=query.hasta) throw new Error('Selecciona un inicio y un fin posterior. El fin no se incluye.'); path=mode==='cliente'?'/clientes/'+encodeURIComponent($('history-client').value.trim().toUpperCase())+'/facturas':'/cajas/'+encodeURIComponent($('history-box').value)+'/facturas'; }
      state.history={rows:[],cursor:null,query,path,epoch:state.history.epoch+1,busy:false};
    }
    epoch=state.history.epoch; const parameters={...state.history.query}; if(more&&state.history.cursor) parameters.cursor=state.history.cursor;
    state.history.busy=true; renderHistory(); const data=await api.request(state.history.path+'?'+new URLSearchParams(parameters));
    if(epoch!==state.history.epoch) return;
    state.history.rows=merge(more?state.history.rows:[],data.items,'factura_id'); state.history.cursor=data.next_cursor;
  } catch(error){ if(epoch===null||epoch===state.history.epoch) report(error); }
  finally { if(epoch===null||epoch===state.history.epoch) {state.history.busy=false; renderHistory();} }
}
function showReceipt(invoice) {
  validateInvoice(invoice);
  const paper=el('article',null,'receipt-paper'), brand=el('div',null,'receipt-brand'), logo=el('div'); logo.append(el('h3','Folio'),el('p','Facturación local · COP')); brand.append(logo,el('span','COMPROBANTE ACADÉMICO','receipt-tag')); paper.append(brand);
  const reference=el('div',null,'receipt-reference'); reference.append(el('strong',invoice.referencia),el('p',dateText(invoice.fecha_utc)+' · hora de Colombia')); paper.append(reference);
  const info=el('div',null,'receipt-info'), customer=el('div'), terminal=el('div'); customer.append(el('span','CLIENTE'),el('strong',invoice.cliente.nombre),el('p',invoice.cliente.tipo_documento==='GENERAL'?'Cliente general':invoice.cliente.tipo_documento+' '+invoice.cliente.numero_documento)); terminal.append(el('span','ATENDIDO POR'),el('strong',invoice.operador_declarado),el('p','Caja '+invoice.caja_id)); info.append(customer,terminal); paper.append(info);
  const scroll=el('div',null,'table-scroll'), table=el('table'), head=el('thead'), headings=el('tr'); ['Producto','Cant.','Precio unit.','Impuesto','Total'].forEach(text=>headings.append(el('th',text))); head.append(headings); const body=el('tbody');
  invoice.lineas.forEach(line=>{ const row=el('tr'); row.append(cell(line.nombre),cell(String(line.cantidad)),cell(money(line.precio_unitario_centavos)),cell(money(line.impuesto_centavos)),cell(money(line.total_centavos))); body.append(row); }); table.append(head,body); scroll.append(table); paper.append(scroll);
  const sum=el('div',null,'receipt-total'); for(const [label,value] of [['Subtotal',invoice.subtotal_centavos],['Impuestos',invoice.impuestos_centavos],['Total COP',invoice.total_centavos]]) { const row=el('div'); row.append(el('span',label),el('strong',money(value))); sum.append(row); } paper.append(sum);
  const foot=el('div',null,'receipt-footer'); foot.append(el('p','Prototipo académico · No válido como factura fiscal'),el('p','Los datos y precios corresponden a la venta registrada.')); paper.append(foot); $('receipt-content').replaceChildren(paper); if(!$('receipt-dialog').open) $('receipt-dialog').showModal();
}
async function openReceipt(id) { try { showReceipt(await api.request('/facturas/'+encodeURIComponent(id))); } catch(error){ report(error); } }

document.querySelectorAll('[data-view]').forEach(node=>node.addEventListener('click',()=>showView(node.dataset.view)));
document.querySelectorAll('[data-close]').forEach(node=>node.addEventListener('click',()=>$(node.dataset.close).close()));
$('product-search').addEventListener('input',renderProducts); $('admin-product-search').addEventListener('input',renderProducts); $('client-search').addEventListener('input',renderCustomers);
for(const id of ['refresh-products','admin-refresh-products']) $(id).addEventListener('click',()=>loadProducts());
for(const id of ['load-products','admin-more-products']) $(id).addEventListener('click',()=>loadProducts(true));
$('refresh-clients').addEventListener('click',()=>loadClients());
for(const id of ['more-clients','more-sale-clients']) $(id).addEventListener('click',()=>loadClients(true));
$('operator').addEventListener('input',()=>{ if(!isLocked()) try{commit({...state.draft,operator:$('operator').value});}catch(error){report(error);} });
$('customer').addEventListener('change',()=>{ if(!isLocked()) try{commit({...state.draft,customer:$('customer').value});}catch(error){report(error);} });
$('box').addEventListener('change',()=>{ if(!state.draft.pending&&!state.draft.lines.length) {notice('');loadBox($('box').value);} });
$('confirm-sale').addEventListener('click',confirmSale); $('review-sale').addEventListener('click',reviewSale);
$('clear-cart').addEventListener('click',()=>{ if(!isLocked()) try{commit({...state.draft,lines:[]});renderProducts();notice('Borrador vacío.');}catch(error){report(error);} });
$('new-product').addEventListener('click',()=>openProduct()); $('new-client').addEventListener('click',()=>openClient()); $('quick-client').addEventListener('click',()=>openClient(null,true));
$('editor-form').addEventListener('submit',saveEditor); $('refresh-health').addEventListener('click',health); $('last-receipt').addEventListener('click',()=>{ if(state.draft.lastReceipt) openReceipt(state.draft.lastReceipt.factura_id); });
$('print-receipt').addEventListener('click',()=>window.print());
$('history-kind').addEventListener('change',historyMode); for(const id of ['history-day','history-client','history-box','history-from','history-until']) $(id).addEventListener('change',resetHistory);
$('history-form').addEventListener('submit',event=>{event.preventDefault();loadHistory();}); $('more-history').addEventListener('click',()=>loadHistory(true));
window.addEventListener('storage',event=>{ if(event.key===KEY_PREFIX+state.draft.box) {state.foreign=true;report(new Error('Esta caja cambió en otra pestaña. Recarga la página para recuperar su estado antes de continuar.'));renderCart();renderProducts();} });
window.addEventListener('hashchange',()=>showView(location.hash.slice(1)));
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&state.view==='venta'&&!$('editor').open&&!$('receipt-dialog').open){event.preventDefault();$('product-search').focus();}});

async function start() {
  $('top-date').textContent=new Intl.DateTimeFormat('es-CO',{timeZone:'America/Bogota',weekday:'long',day:'numeric',month:'long'}).format(new Date());
  const today=dayInBogota(); $('history-day').value=$('history-from').value=today; $('history-until').value=nextDay(today); historyMode(); showView(location.hash.slice(1)||'venta'); renderLogs();
  try {
    const data=await api.request('/cajas?limit=25'); state.boxes=data.items;
    const requested=new URLSearchParams(location.search).get('caja'), active=state.boxes.filter(b=>b.activo);
    $('box').replaceChildren(...state.boxes.map(b=>{const option=el('option',b.nombre||b.caja_id);option.value=b.caja_id;option.disabled=!b.activo;return option;}));
    $('history-box').replaceChildren(...state.boxes.map(b=>{const option=el('option',b.nombre||b.caja_id);option.value=b.caja_id;return option;}));
    const box=requested||active[0]?.caja_id||'c01'; loadBox(box);
    if(!state.boxes.some(b=>b.caja_id===box&&b.activo)) {state.blocked=true;notice('La caja seleccionada no está disponible. Selecciona una caja activa.',true);renderCart();}
  } catch(error){state.blocked=true;report(error);renderCart();}
  await Promise.allSettled([loadProducts(),loadClients(),health()]); renderProducts(); renderCart();
}
start().catch(report);
