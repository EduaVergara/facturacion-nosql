"""Verifica el servidor web real y dos ventas ficticias a traves de su proxy."""
import argparse
import json
import sys
import urllib.request
from urllib.parse import quote
import uuid
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
if __package__:
    from .local_http import request_json
else:
    from local_http import request_json


def verify(base='http://frontend:8080'):
    base=base.rstrip('/')
    for path,mime in [('/','text/html'),('/app.mjs','text/javascript'),('/domain.mjs','text/javascript'),('/api.mjs','text/javascript'),('/styles.css','text/css')]:
        with urllib.request.urlopen(base+path,timeout=15) as response:
            assert response.status==200 and mime in response.headers['Content-Type']
            assert len(response.read())>100
            assert "script-src 'self'" in response.headers['Content-Security-Policy']
    request=lambda path,**options:request_json(base+'/api'+path,**options)
    assert request_json(base+'/ready')[1]['servicio']=='folio-web'
    health=request('/health',expected=(200,503))[1]
    assert health['dynamodb']['estado']=='ok' and health['etapa']==6
    products=request('/productos?limit=25')[1]['items']
    product=next(p for p in products if p['activo'])
    product=request('/productos/'+product['producto_id'])[1]
    customer=request('/clientes/'+quote('CC#90000001',safe=''))[1]
    assert customer['cliente_id']=='CC#90000001'
    boxes=request('/cajas?limit=25')[1]['items']
    assert all(any(b['caja_id']==identifier and b['activo'] for b in boxes) for identifier in ('c01','c02'))
    bodies=[{'solicitud_id':str(uuid.uuid4()),'caja_id':box,'operador_declarado':'Prueba web etapa 6','cliente_id':customer['cliente_id'],
             'lineas':[{'producto_id':product['producto_id'],'cantidad':1,'version_esperada':product['version']}]} for box in ('c01','c02')]
    def sell(body):
        first=request('/facturas',method='POST',data=body,expected=(200,201))[1]
        again=request('/facturas',method='POST',data=body)[1]
        assert again['replayed'] and first['factura']==again['factura']
        invoice=first['factura']
        detail=request('/facturas/'+invoice['factura_id'])[1]
        assert detail==invoice and detail['caja_id']==body['caja_id']
        return invoice
    with ThreadPoolExecutor(max_workers=2) as pool: invoices=list(pool.map(sell,bodies))
    assert len({f['factura_id'] for f in invoices})==2
    day=invoices[0]['fecha_local']
    request('/facturas?fecha='+day+'&limit=25')
    until=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
    request('/clientes/'+quote(customer['cliente_id'],safe='')+'/facturas?desde='+day+'&hasta='+until+'&limit=25')
    return {'estado':'ok','archivos_y_tipo_mime':'ok','proxy_api_mismo_origen':'ok','cliente_con_identificacion':'ok',
            'dos_cajas_por_servidor_web':'ok','reintento_sin_duplicados':'ok','comprobante_persistido':'ok','historial_por_proxy':'ok',
            'ventas_ficticias_creadas':2,'facturas':[f['factura_id'] for f in invoices]}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://frontend:8080');args=parser.parse_args()
    try: print(json.dumps(verify(args.base),indent=2,ensure_ascii=False))
    except Exception as exc:
        print(f'Verificacion web incompleta ({type(exc).__name__}): {exc}',file=sys.stderr);sys.exit(1)
