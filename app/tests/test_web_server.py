"""Proxy local: rutas limitadas, bytes idempotentes y errores sin reenvios."""
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
from scripts import serve_frontend as web


class WebServerTests(unittest.TestCase):
    def handler(self, path='/api/facturas', method='POST', raw=b'{ "solicitud_id": "misma" }', headers=None):
        handler=object.__new__(web.FrontendHandler)
        handler.path=path; handler.command=method
        handler.headers={'Host':'localhost:8080','Content-Length':str(len(raw)),**(headers or {})}
        handler.rfile=io.BytesIO(raw)
        handler.server=SimpleNamespace(outputs=Path('outputs.json'),endpoint='http://emulador:4566',public=Path(__file__).resolve().parents[2]/'frontend')
        handler.send=Mock()
        return handler

    def test_encoded_customer_and_query_are_preserved(self):
        self.assertEqual(web.route_path('/api/clientes/CC%230001/facturas?desde=2026-01-15&hasta=2026-01-16','GET'),'/clientes/CC%230001/facturas?desde=2026-01-15&hasta=2026-01-16')

    def test_only_business_routes_and_methods(self):
        for path,method in [('/api/health','POST'),('/api/cajas/c01','PUT'),('/api/facturas/1','DELETE'),('/api/_localstack/health','GET'),('/api/clientes/%2e%2e','GET'),('/api/clientes/a%2fb','GET'),('/api/clientes/a%5cb','GET'),('/api/clientes/a%00b','GET'),('//otro/api/health','GET'),('https://otro/api/health','GET'),('/app/local-config.json','GET')]:
            with self.subTest(path=path,method=method), self.assertRaises(ValueError): web.route_path(path,method)

    def test_upstream_cannot_target_external_or_admin_service(self):
        self.assertEqual(web.upstream_base('http://emulador:4566','abc123'),'http://emulador:4566/restapis/abc123/prod/_user_request_')
        for endpoint in ['https://emulador:4566','http://example.com','http://user@emulador:4566','http://emulador:4566/admin','http://emulador:4566?url=evil']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError): web.upstream_base(endpoint,'abc123')
        with self.assertRaises(ValueError): web.upstream_base('http://emulador:4566','../admin')

    def test_post_forwards_original_bytes_and_source_headers_once(self):
        handler=self.handler(); response=Mock(status=201,headers={'Content-Type':'application/json','X-Data-Source':'dynamodb','X-Cache':'bypass'})
        response.read.return_value=b'{"factura":{}}'
        response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
        with patch.object(web,'load_outputs',return_value={'ApiId':'abc123'}), patch.object(web.urllib.request,'urlopen',return_value=response) as request:
            handler.api()
        self.assertEqual(request.call_count,1)
        forwarded=request.call_args.args[0]
        self.assertEqual(forwarded.data,b'{ "solicitud_id": "misma" }')
        self.assertEqual(forwarded.full_url,'http://emulador:4566/restapis/abc123/prod/_user_request_/facturas')
        self.assertEqual(handler.send.call_args.args[:2],(201,b'{"factura":{}}'))
        self.assertEqual(handler.send.call_args.args[3]['X-Cache'],'bypass')

    def test_timeout_does_not_resend_sale(self):
        handler=self.handler()
        with patch.object(web,'load_outputs',return_value={'ApiId':'abc123'}),patch.object(web.urllib.request,'urlopen',side_effect=TimeoutError()) as request: handler.api()
        self.assertEqual(request.call_count,1); self.assertEqual(handler.send.call_args.args[0],504)

    def test_http_conflict_body_is_not_rewritten(self):
        handler=self.handler(); error=urllib.error.HTTPError('http://emulador',409,'Conflict',{'Content-Type':'application/json'},io.BytesIO(b'{"codigo":"CATALOGO_CAMBIO"}'))
        with patch.object(web,'load_outputs',return_value={'ApiId':'abc123'}),patch.object(web.urllib.request,'urlopen',side_effect=error): handler.api()
        self.assertEqual(handler.send.call_args.args[:2],(409,b'{"codigo":"CATALOGO_CAMBIO"}'))

    def test_cross_site_oversize_and_invalid_lengths_never_reach_upstream(self):
        cases=[({'Origin':'https://otro'},403),({'Sec-Fetch-Site':'cross-site'},403),({'Content-Length':'65537'},413),({'Content-Length':'-1'},400),({'Content-Length':'x'},400),({'Transfer-Encoding':'chunked'},400)]
        for headers,status in cases:
            with self.subTest(headers=headers),patch.object(web.urllib.request,'urlopen') as request:
                handler=self.handler(headers=headers); handler.api(); request.assert_not_called(); self.assertEqual(handler.send.call_args.args[0],status)

    def test_missing_outputs_returns_service_error(self):
        handler=self.handler()
        with patch.object(web,'load_outputs',side_effect=FileNotFoundError()),patch.object(web.urllib.request,'urlopen') as request: handler.api()
        request.assert_not_called(); self.assertEqual(handler.send.call_args.args[0],503)

    def test_private_files_are_not_served(self):
        for path in ['/app/cdk-outputs.json','/.env','/test/domain.test.mjs','/../app/local-config.json']:
            handler=self.handler(path,method='GET');handler.do_GET();self.assertEqual(handler.send.call_args.args[0],404)

    def test_ready_does_not_claim_database_health(self):
        handler=self.handler('/ready',method='GET');handler.do_GET()
        self.assertEqual(handler.send.call_args.args[1],{'estado':'ok','servicio':'folio-web','etapa':6})
