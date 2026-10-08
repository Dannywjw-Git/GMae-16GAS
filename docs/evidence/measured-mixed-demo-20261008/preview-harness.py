"""Temporary layout-only harness. No production API, task DB or GPU mutations."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json, os, sys, threading
REPO = Path(__file__).resolve().parents[1] / 'GMae-16GAS'
APP = REPO / '16gb-ai-studio/vram-console'
sys.path.insert(0, str(APP))
os.environ['GMAE_PROFILE_DIR'] = str(APP / 'data/profiles-mixed')
from engine.measured_presets import public_catalog
catalog = public_catalog()
Path(__file__).with_name('measured-preset-catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
fixture = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>GMae 队列布局核验</title>
<link rel="stylesheet" href="/css/variables.css"><link rel="stylesheet" href="/css/base.css">
<link rel="stylesheet" href="/css/layout.css"><link rel="stylesheet" href="/css/components.css">
<link rel="stylesheet" href="/css/pages/common.css">
<body style="padding:24px"><p style="background:#fef3c7;color:#78350f;padding:12px">布局核验：预设来自本机已安装证据；任务与输出为 UI 测试样例，未执行 GPU 任务。</p><div id="app-content"></div>
<script src="/js/core/utils.js"></script><script src="/js/components/icons.js"></script>
<script>const Router={current:'/queue'}, Toast={success:console.log,error:console.error,warning:console.warn},Pages={}, Modal={};
const API={getMeasuredPresets:async()=>({...await (await fetch('/catalog.json')).json(),ok:true}),
getRegistry:async()=>({comfyui_models:[{id:'SDXL',name:'SDXL',workflow:'sdxl.json',category:'image'}]}),
previewResources:async()=>({allowed:false,reason:'布局预览不连接 GPU，不能验证实时准入'}),
getQueue:async()=>({ok:true,tasks:[{id:'layout-fixture',model:'qwen3.5:9b',source:'ollama',status:'done',created:1791446400,
result:{response:'UI 测试文本（非模型输出） <script>unsafe</scr'+'ipt>',metrics:{eval_count:24}}}],coordination:{}}),
submitMeasuredPreset:async()=>({ok:false,error:{message:'布局预览不能提交 GPU 任务'}})};</script>
<script src="/js/pages/queue.js"></script><script>Pages.queue();</script></body></html>'''
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(APP/'web'),**kwargs)
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path in ('/','/catalog.json'):
            payload = fixture.encode() if self.path=='/' else json.dumps(catalog,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8' if self.path=='/' else 'application/json');self.end_headers();self.wfile.write(payload)
        else: super().do_GET()
    def do_POST(self):
        if self.path=='/__stop':
            self.send_response(200);self.end_headers();threading.Thread(target=server.shutdown,daemon=True).start()
        else: self.send_error(405)
server=ThreadingHTTPServer(('127.0.0.1',18719),Handler)
timer=threading.Timer(300,server.shutdown);timer.daemon=True;timer.start()
print(json.dumps(dict(port=18719,presets=len(catalog['presets']),rejected=catalog['rejected_count'])),flush=True)
try:server.serve_forever()
finally:server.server_close();timer.cancel()
