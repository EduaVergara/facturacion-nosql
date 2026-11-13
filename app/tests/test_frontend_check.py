"""Ejecuta el comprobador web contra los handlers reales en memoria."""
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from history_support import HistoryMemoryRepository
from catalogo.handler import main as catalog
from facturacion.handler import main as invoices
from scripts import check_frontend
from scripts.seed_demo import seed


class FrontendCheckTests(unittest.TestCase):
    def test_two_boxes_replay_details_and_history_contract(self):
        repo=HistoryMemoryRepository();repo.items={};seed(repo)
        def request(url,method='GET',data=None,expected=(200,),**kwargs):
            parsed=urlsplit(url)
            if parsed.path=='/ready': return 200,{'servicio':'folio-web'},{}
            path=parsed.path.removeprefix('/api/').split('/')
            if path==['health']:return 200,{'etapa':6,'dynamodb':{'estado':'ok'}},{}
            route='/'+path[0]+('/{id}' if len(path)>1 else '')+('/'+path[2] if len(path)>2 else '')
            event={'httpMethod':method,'resource':route,'pathParameters':{'id':path[1] if len(path)>1 else ''},
                   'queryStringParameters':{k:v[-1] for k,v in parse_qs(parsed.query).items()},'headers':{'Content-Type':'application/json'},'body':None if data is None else json.dumps(data)}
            handler=invoices if path[0]=='facturas' or len(path)>2 else catalog
            result=handler(event,None,repo,None)
            payload=json.loads(result['body'])
            self.assertIn(result['statusCode'],expected,(route,payload))
            return result['statusCode'],payload,result.get('headers',{})
        class Asset(io.BytesIO):
            status=200
            headers={'Content-Security-Policy':"script-src 'self'"}
        def asset(url,**kwargs):
            suffix=urlsplit(url).path
            response=Asset(b'asset'*100)
            response.headers={**response.headers,'Content-Type':'text/html' if suffix=='/' else 'text/css' if suffix.endswith('.css') else 'text/javascript'}
            return response
        with patch.object(check_frontend,'request_json',side_effect=request),patch.object(check_frontend.urllib.request,'urlopen',side_effect=asset):
            result=check_frontend.verify('http://frontend:8080')
        self.assertEqual(result['estado'],'ok')
        self.assertEqual(result['ventas_ficticias_creadas'],2)
        documents=[item for item in repo.items.values() if item.get('tipo_entidad')=='FACTURA']
        self.assertEqual(len(documents),2)
        self.assertEqual({f['caja_id'] for f in documents},{'c01','c02'})
