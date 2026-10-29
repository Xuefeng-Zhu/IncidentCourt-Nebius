"""Health-only judge-ledger bootstrap: HTTP never initializes storage."""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from deploy.instacloud.bootstrap_guard import block_outbound, reject_credentials


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        body = json.dumps({'mode':'judge-ledger-bootstrap-only',
                           'volume_mounted':os.path.ismount('/data'),
                           'provider_calls':0}).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(body)


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
        super().server_bind()


def main():
    reject_credentials(os.environ)
    if os.environ.get('JUDGE_BOOTSTRAP_HEALTH') != '1' or os.environ.get('PORT') != '8080':
        raise ValueError('Explicit judge bootstrap-health mode and port 8080 are required.')
    block_outbound()
    server = DualStackServer(('::',8080),Handler)
    print('Judge-ledger bootstrap health endpoint running; no provider calls.',flush=True)
    try: server.serve_forever()
    finally: server.server_close()


if __name__ == '__main__': main()
