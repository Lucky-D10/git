"""Independent loopback waiting page; survives backend startup/restart delays."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.request import urlopen

HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Focus 正在启动</title><style>body{background:#0b1220;color:#e7eef5;font:22px system-ui;padding:12vh 8vw}p{font-size:17px;color:#aec2d5}button{font:inherit;padding:12px}small{display:block;margin-top:20px}</style><h1>Focus · 正在连接后台</h1><p id="status">动力保持关闭。等待本地服务就绪后进入设备准备。</p><button onclick="check()">重新检查</button><small>长时间未就绪：按 Alt+F4 返回桌面，检查 focus-web 服务日志。</small><script>let busy=false;async function check(){if(busy)return;busy=true;try{let r=await(await fetch('/ready')).json();if(r.ready)location.replace('http://127.0.0.1:8000/');else document.querySelector('#status').textContent='后台尚未就绪，正在自动重试。动力保持关闭。';}catch{}finally{busy=false}}setInterval(check,1000);check();</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/ready':
            ready = False
            try:
                with urlopen('http://127.0.0.1:8000/api/health', timeout=.7) as response:
                    ready = bool(json.load(response).get('ready'))
            except (OSError, ValueError):
                pass
            content, kind = json.dumps({'ready': ready}).encode(), 'application/json'
        else:
            content, kind = HTML.encode(), 'text/html; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8001), Handler).serve_forever()
