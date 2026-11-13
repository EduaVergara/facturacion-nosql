"""Servidor local de archivos y proxy limitado a las rutas de facturacion."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit
import urllib.error
import urllib.request

if __package__:
    from .local_outputs import load_outputs
else:
    from local_outputs import load_outputs

STATIC = {"/":"index.html", "/index.html":"index.html", "/app.mjs":"app.mjs",
          "/domain.mjs":"domain.mjs", "/api.mjs":"api.mjs", "/styles.css":"styles.css"}
MAX_BODY = 65536


def upstream_base(endpoint, api_id):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"emulador","localhost","127.0.0.1"}
        or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        or not re.fullmatch(r"[a-z0-9]{1,32}", api_id)):
        raise ValueError("El frontend requiere el emulador HTTP local y un ApiId valido")
    return endpoint.rstrip('/') + f"/restapis/{api_id}/prod/_user_request_"


def route_path(raw_path, method):
    path = urlsplit(raw_path)
    if path.scheme or path.netloc or len(raw_path) > 12000 or not path.path.startswith("/api/"):
        raise ValueError("Ruta no admitida")
    raw_parts = path.path[len('/api/'):].split('/')
    parts = [unquote(part) for part in raw_parts]
    if any(not part or part in {'.','..'} or any(c in part for c in '/\\') or any(ord(c)<32 for c in part) for part in parts):
        raise ValueError("Segmento no admitido")
    name = parts[0]
    methods = set()
    if parts == ['health']:
        methods={'GET'}
    elif name in {'productos','clientes'}:
        if len(parts)==1: methods={'GET','POST'}
        elif len(parts)==2: methods={'GET','PUT'}
        elif len(parts)==3 and name=='clientes' and parts[2]=='facturas': methods={'GET'}
    elif name=='cajas':
        if len(parts)==1 or (len(parts)==3 and parts[2]=='facturas'): methods={'GET'}
    elif name=='facturas':
        if len(parts)==1: methods={'GET','POST'}
        elif len(parts)==2: methods={'GET'}
    if method not in methods:
        raise ValueError("Ruta o metodo no admitido")
    return '/' + '/'.join(quote(part,safe='') for part in parts) + ('?'+path.query if path.query else '')


class FrontendServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self, address, public, outputs, endpoint):
        self.public = Path(public).resolve()
        self.outputs = Path(outputs)
        self.endpoint = endpoint
        super().__init__(address, FrontendHandler)


class FrontendHandler(BaseHTTPRequestHandler):
    server_version='FolioLocal/6'
    def send(self,status,body,content_type='application/json; charset=utf-8',extra=None):
        if isinstance(body,dict): body=json.dumps(body,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for key,value in (extra or {}).items(): self.send_header(key,value)
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError): pass

    def api(self):
        origin = self.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {'http','https'} or parsed.netloc.lower() != self.headers.get('Host','').lower():
                self.send(403,{'error':'El origen de esta peticion no esta permitido'}); return
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.send(403,{'error':'La API se utiliza desde la interfaz del comercio'}); return
        if self.headers.get('Transfer-Encoding'):
            self.send(400,{'error':'Usa Content-Length para el cuerpo JSON'}); return
        try:
            target = route_path(self.path,self.command)
            length = int(self.headers.get('Content-Length','0'))
            if length < 0: raise ValueError()
        except ValueError:
            self.send(400,{'error':'Ruta, metodo o longitud de peticion no validos'}); return
        if length > MAX_BODY:
            self.send(413,{'error':'El cuerpo supera el limite de 64 KiB'}); return
        raw = self.rfile.read(length) if length else None
        try:
            outputs = load_outputs(self.server.outputs)
            base = upstream_base(self.server.endpoint,outputs['ApiId'])
        except (ValueError,KeyError,OSError,RuntimeError):
            self.send(503,{'error':'La API local aun no esta configurada. Ejecuta la verificacion del proyecto.'}); return
        headers = {'Content-Type':self.headers.get('Content-Type','application/json')}
        request = urllib.request.Request(base+target,data=raw,method=self.command,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=35) as response:
                status,body,response_headers = response.status,response.read(),response.headers
        except urllib.error.HTTPError as error:
            try: status,body,response_headers=error.code,error.read(),error.headers
            finally: error.close()
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError):
            self.send(504,{'error':'No se recibio confirmacion del servidor. Conserva la solicitud de venta y vuelve a intentarla.'}); return
        extra={key:response_headers[key] for key in ('X-Data-Source','X-Cache') if key in response_headers}
        self.send(status,body,response_headers.get('Content-Type','application/json; charset=utf-8'),extra)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/ready':
            self.send(200,{'estado':'ok','servicio':'folio-web','etapa':6}); return
        if path.startswith('/api/'):
            self.api(); return
        filename=STATIC.get(path)
        if filename is None:
            self.send(404,{'error':'Archivo no encontrado'}); return
        try: body=(self.server.public/filename).read_bytes()
        except OSError:
            self.send(404,{'error':'No se encontraron los archivos de la interfaz'}); return
        content_type=('text/html; charset=utf-8' if filename.endswith('.html') else
                      'text/css; charset=utf-8' if filename.endswith('.css') else 'text/javascript; charset=utf-8')
        self.send(200,body,content_type)

    def do_POST(self): self.api()
    def do_PUT(self): self.api()
    def do_DELETE(self): self.send(405,{'error':'Metodo no admitido'})
    def do_OPTIONS(self): self.send(405,{'error':'La interfaz y su API comparten el mismo origen'})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--public',default=str(Path(__file__).resolve().parents[2]/'frontend'))
    parser.add_argument('--outputs',default=str(Path(__file__).resolve().parents[1]/'cdk-outputs.json'))
    parser.add_argument('--endpoint',default=os.environ.get('AWS_ENDPOINT_URL','http://emulador:4566'))
    args=parser.parse_args()
    server=FrontendServer((args.host,args.port),args.public,args.outputs,args.endpoint)
    print(f'Folio local: http://{args.host}:{server.server_address[1]}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
