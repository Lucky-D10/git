"""Independent loopback waiting page; survives backend startup/restart delays."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.request import urlopen

HTML = '''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Focus 正在启动</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(130deg,#f9fdff,#eaf5ff);color:#101b50;font:18px "Microsoft YaHei",system-ui,sans-serif;overflow:hidden}
header{height:64px;padding:16px 28px;font-size:27px;font-weight:800;display:flex;align-items:center;gap:10px}
.logo{width:33px;height:33px;background:#188fff;border-radius:50%;display:grid;place-items:center;color:white;font-size:24px}
main{position:relative;z-index:1;text-align:center;padding:14px 20px}h1{font-size:29px;margin:16px 0 9px}p{color:#59769e;font-size:16px;margin:9px 0}
.orb{width:119px;height:119px;margin:auto;border-radius:50%;background:linear-gradient(145deg,#a9d3ff,#2988f6);box-shadow:0 0 0 18px #e1f0ff,0 0 0 35px #edf6ff;display:grid;place-items:center}
.orb svg{width:63px;height:63px;color:white}.dots{margin-top:26px;letter-spacing:9px;color:#2b96f8;font-size:18px}
button{font:inherit;font-size:16px;color:#185590;border:1px solid #82b5e7;border-radius:30px;background:#faffff;padding:11px 28px;min-height:46px;cursor:pointer;margin:10px 0}
button:focus-visible{outline:3px solid #156aba;outline-offset:3px}footer{position:relative;z-index:1;text-align:center;font-size:11px;color:#627c9f;padding:8px 16px}
.wave{position:fixed;bottom:-145px;left:-10%;width:130%;height:230px;border-radius:50%;background:#daefff;transform:rotate(-7deg)}.wave.second{background:#cae6fa;bottom:-178px;transform:rotate(8deg)}
@media(max-width:500px){header{height:75px}main{padding-top:45px}h1{font-size:25px}p{font-size:14px}.orb{width:105px;height:105px}}
</style><header><span class="logo">∿</span> FOCUS</header><main>
<div class="orb"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M10 4C7 1 3 5 5 8c-4 1-3 6 0 7-2 4 3 7 5 3ZM14 4c3-3 7 1 5 4 4 1 3 6 0 7 2 4-3 7-5 3ZM7 7l1 3-2 3m11-6-1 3 2 3M12 3v18"/></svg></div>
<div class="dots" aria-hidden="true">● ● ●</div><h1>正在连接训练服务</h1>
<p id="status" role="status">正在连接后台，准备好后进入首页。动力保持关闭。</p><button onclick="check()">重新检查</button>
</main><div class="wave"></div><div class="wave second"></div><footer>无需联网 · 长时间未就绪可按 Alt+F4 返回桌面，请老师检查服务日志。</footer>
<script>let busy=false;async function check(){if(busy)return;busy=true;try{let r=await(await fetch('/ready')).json();if(r.ready)location.replace('http://127.0.0.1:8000/');else document.querySelector('#status').textContent='正在连接后台，准备好后进入首页。动力保持关闭。';}catch{}finally{busy=false}}setInterval(check,1000);check();</script></html>'''


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
