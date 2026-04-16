"""
Dashboard Server - Servidor local para Herramientas Financieras Adstter
Sirve archivos estaticos y permite ejecutar scripts Python/BAT desde el dashboard.
Puerto: 8787
"""

import http.server
import socketserver
import json
import subprocess
import os
import sys
import shlex
import threading
import urllib.parse

PORT = 8787
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Scripts permitidos (whitelist por seguridad)
ALLOWED_SCRIPTS = {
    'asistente_iva/ejecutar_asistente.bat',
    'asistente_iva/ejecutar_asistente.py',
    'asistente_facturacion/EJECUTAR_ASISTENTE.bat',
    'asistente_anulacion_sat/ejecutar_anulacion.bat',
    'generar_excel_sat.bat',
    'renovar_token.py',
    'actualizar-datos.py',
    'generar_excel_sat.py',
    'generar_excel_zoho_automatico.py',
}


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """Handler que sirve archivos y expone API para ejecutar scripts."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        # No cachear HTML ni JS para que siempre sirva la version mas reciente
        path = urllib.parse.urlparse(self.path).path
        if path.endswith(('.html', '.js', '.css')):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Ruta raiz redirige al dashboard
        if parsed.path == '/':
            self.send_response(302)
            self.send_header('Location', '/dashboard.html')
            self.end_headers()
            return

        # API: estado del servidor
        if parsed.path == '/api/status':
            self.send_json({'status': 'ok', 'pid': os.getpid()})
            return

        # Servir archivos estaticos
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        # Abrir script en terminal interactiva (nueva ventana cmd)
        if parsed.path == '/api/launch':
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({'success': False, 'error': 'JSON invalido'}, 400)
                return

            script = data.get('script', '')
            normalized = script.replace('\\', '/')
            if normalized not in ALLOWED_SCRIPTS:
                self.send_json({'success': False, 'error': f'Script no autorizado: {script}'}, 403)
                return

            full_path = os.path.join(BASE_DIR, script)
            if not os.path.exists(full_path):
                self.send_json({'success': False, 'error': f'Archivo no encontrado: {script}'}, 404)
                return

            work_dir = os.path.dirname(full_path) or BASE_DIR
            filename = os.path.basename(full_path)

            # Abrir en nueva ventana de cmd para interaccion del usuario.
            # Pasar el comando como string unico para que cmd.exe interprete
            # correctamente las comillas alrededor de rutas con espacios.
            if filename.endswith('.bat'):
                cmdline = f'cmd /k call "{filename}"'
            elif filename.endswith('.py'):
                cmdline = f'cmd /k ""{sys.executable}" "{filename}""'
            else:
                self.send_json({'success': False, 'error': 'Tipo de archivo no soportado'}, 400)
                return

            subprocess.Popen(
                cmdline,
                cwd=work_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )

            self.send_json({'success': True, 'message': 'Script abierto en terminal'})
            return

        if parsed.path == '/api/execute':
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({'success': False, 'error': 'JSON invalido'}, 400)
                return

            script = data.get('script', '')

            # Validar que el script este en la whitelist
            normalized = script.replace('\\', '/')
            if normalized not in ALLOWED_SCRIPTS:
                self.send_json({
                    'success': False,
                    'error': f'Script no autorizado: {script}'
                }, 403)
                return

            # Determinar comando y directorio de trabajo
            full_path = os.path.join(BASE_DIR, script)
            if not os.path.exists(full_path):
                self.send_json({
                    'success': False,
                    'error': f'Archivo no encontrado: {script}'
                }, 404)
                return

            work_dir = os.path.dirname(full_path) or BASE_DIR
            filename = os.path.basename(full_path)

            # Parsear argumentos adicionales del campo cmd (solo flags seguras)
            extra_args = []
            raw_cmd = data.get('cmd', '')
            if raw_cmd and filename.endswith('.py'):
                try:
                    parts = shlex.split(raw_cmd)
                except ValueError:
                    parts = raw_cmd.split()
                # Extraer solo flags permitidas despues del nombre del script
                SAFE_FLAGS = {'--periodo', '--anio', '--mes', '--fecha-inicio', '--fecha-fin',
                              '--solo-zoho', '--no-abrir', '--abrir'}
                skip_next = False
                for i, part in enumerate(parts):
                    if skip_next:
                        skip_next = False
                        continue
                    if part in SAFE_FLAGS:
                        extra_args.append(part)
                        # Si el siguiente elemento es un valor (no empieza con --)
                        if i + 1 < len(parts) and not parts[i+1].startswith('--'):
                            extra_args.append(parts[i+1])
                            skip_next = True

            if filename.endswith('.bat'):
                cmd = ['cmd', '/c', filename]
            elif filename.endswith('.py'):
                cmd = [sys.executable, filename] + extra_args
            else:
                self.send_json({'success': False, 'error': 'Tipo de archivo no soportado'}, 400)
                return

            # Ejecutar en un thread para no bloquear
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            # Timeout largo (10 min) para scripts con Playwright/browser automation
            script_timeout = 600

            try:
                result = subprocess.run(
                    cmd,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=script_timeout,
                    encoding='utf-8',
                    errors='replace'
                )
                response = {
                    'success': result.returncode == 0,
                    'returncode': result.returncode,
                    'output': result.stdout + ('\n' + result.stderr if result.stderr else ''),
                    'error': result.stderr if result.returncode != 0 else None
                }
            except subprocess.TimeoutExpired:
                response = {
                    'success': False,
                    'error': f'El script excedio el tiempo limite de {script_timeout} segundos.',
                    'returncode': -1,
                    'output': ''
                }
            except Exception as e:
                response = {
                    'success': False,
                    'error': str(e),
                    'returncode': -1,
                    'output': ''
                }

            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            return

        self.send_json({'error': 'Ruta no encontrada'}, 404)

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        # Log simplificado
        if '/api/' in (args[0] if args else ''):
            print(f"  API: {args[0]}")


def main():
    print("=" * 50)
    print("  Dashboard Herramientas Financieras Adstter")
    print("=" * 50)
    print(f"  Directorio: {BASE_DIR}")
    print(f"  Puerto:     {PORT}")
    print(f"  URL:        http://localhost:{PORT}")
    print(f"  Scripts permitidos: {len(ALLOWED_SCRIPTS)}")
    print("=" * 50)
    print("  Presiona Ctrl+C para detener el servidor")
    print()

    # ThreadingHTTPServer: permite atender multiples peticiones en paralelo
    # (indispensable para que health checks respondan mientras se ejecutan scripts)
    class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    server = ThreadedServer(('127.0.0.1', PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor detenido.")
        server.server_close()


if __name__ == '__main__':
    main()
