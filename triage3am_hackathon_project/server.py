"""
Triage3AM Web Server: Ultra-fast, zero-dependency HTTP server with REST API
for raw log ingestion, instant clustering, and interactive UI.
"""

import os
import json
import time
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import argparse
from triage_engine import TriageEngine, export_postmortem_markdown

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
DATASETS_DIR = os.path.join(BASE_DIR, 'datasets')

class TriageRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, enable_cors=False, **kwargs):
        self.enable_cors = enable_cors
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/api/presets':
            self._handle_get_presets()
        elif path == '/api/load-preset':
            preset_name = query.get('name', [''])[0]
            self._handle_load_preset(preset_name)
        elif path == '/api/health':
            self._send_json({'status': 'ok', 'server': 'Triage3AM v2.0'})
        else:
            # Fallback to serving static files
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Safely parse Content-Length
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            self._send_json({'error': 'Invalid Content-Length'}, status=400)
            return

        if content_length > 10 * 1024 * 1024:  # 10 MB limit
            self._send_json({'error': 'Payload too large. Max 10MB.'}, status=413)
            return
            
        if path == '/api/analyze':
            post_data = self.rfile.read(content_length).decode('utf-8', errors='replace')
            content_type = self.headers.get('Content-Type', '')
            
            try:
                if 'application/json' in content_type:
                    body = json.loads(post_data)
                    raw_logs = body.get('logs', '')
                else:
                    raw_logs = post_data

                t0 = time.time()
                engine = TriageEngine()
                report = engine.ingest_logs(raw_logs)
                elapsed = round(time.time() - t0, 3)
                report['summary']['time_to_triage_seconds'] = elapsed
                self._send_json(report)
            except Exception as e:
                print(f"Error during analysis: {e}")
                self._send_json({'error': 'Internal Server Error during analysis.'}, status=500)

        elif path == '/api/export-slack':
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                slack_msg = self._generate_slack_markdown(data)
                self._send_json({'markdown': slack_msg})
            except Exception as e:
                print(f"Error during slack export: {e}")
                self._send_json({'error': 'Internal Server Error during export.'}, status=500)
        elif path == '/api/export-postmortem':
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                md = export_postmortem_markdown(data)
                self._send_json({'markdown': md})
            except Exception as e:
                print(f"Error during postmortem export: {e}")
                self._send_json({'error': 'Internal Server Error during export.'}, status=500)
        else:
            self.send_error(404, "Endpoint not found")

    def _handle_get_presets(self):
        all_presets = [
            {
                'id': 'ecommerce_cascade_10k.log',
                'title': 'Scenario 1: Black Friday Checkout Cascade (10,000 Lines)',
                'description': 'PostgreSQL pool exhaustion cascades into Hikari pool timeout, payment retry storm, and 504 Gateway Timeouts.',
                'services': ['postgres-cluster', 'order-service', 'payment-gateway', 'api-gateway'],
                'lines': 10000,
                'type': 'Database Starvation'
            },
            {
                'id': 'k8s_oom_cascade_10k.log',
                'title': 'Scenario 2: Kubernetes OOMKilled & CrashLoop (10,000 Lines)',
                'description': 'Java Heap OOM kills auth-service pod; kernel oom-killer evicts container, cascading auth failures through API gateway.',
                'services': ['auth-service', 'kubelet', 'user-service', 'api-gateway'],
                'lines': 10000,
                'type': 'Memory Exhaustion'
            },
            {
                'id': 'redis_thundering_herd_10k.log',
                'title': 'Scenario 3: Redis Thundering Herd (10,000 Lines)',
                'description': 'Redis primary failover timeout causes a cache miss thundering herd that exhausts DB connections and leads to 504 Gateway Timeouts.',
                'services': ['redis-cluster', 'cache-proxy', 'product-service', 'search-service', 'api-gateway'],
                'lines': 10000,
                'type': 'Thundering Herd'
            }
        ]
        valid_presets = []
        for p in all_presets:
            if os.path.exists(os.path.join(DATASETS_DIR, p['id'])):
                valid_presets.append(p)
        self._send_json({'presets': valid_presets})

    def _handle_load_preset(self, name: str):
        # Prevent directory traversal
        safe_name = os.path.basename(name)
        preset_path = os.path.join(DATASETS_DIR, safe_name)
        if not os.path.exists(preset_path):
            self._send_json({'error': 'Preset not found'}, status=404)
            return

        with open(preset_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self._send_json({
            'name': safe_name,
            'lines_count': len(content.splitlines()),
            'content': content
        })

    def _generate_slack_markdown(self, report: dict) -> str:
        s = report.get('summary', {})
        incidents = report.get('incidents', [])
        p0 = incidents[0] if incidents else {}

        md = f"""🚨 *[INCIDENT ALERT: SEV-{p0.get('priority', 'P0')}] - {s.get('root_cause_summary', 'Service Outage')}*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Trigger Detected:* `{s.get('outage_started_at', '03:00 UTC')}`
• *Noise Reduction:* `{s.get('total_lines_ingested', 10000)} lines` ➔ `{s.get('actionable_incidents', 3)} root incidents` ({s.get('noise_reduction_percentage', 99.9)}% noise filtered in {s.get('time_to_triage_seconds', 0.2)}s)
• *Blast Radius:* {len(s.get('services_impacted', []))} services affected: `{', '.join(s.get('services_impacted', [])[:5])}`

*Root Cause Hypothesis:*
> {p0.get('diagnosis', {}).get('trigger', 'Underlying dependency failure')}

*Patient Zero (First Anomaly):*
```{p0.get('patient_zero', {}).get('raw', 'N/A')[:200]}```

*Recommended Immediate Action:*
```{p0.get('diagnosis', {}).get('command', 'kubectl get pods -A')}```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_Generated automatically by Triage3AM in {s.get('time_to_triage_seconds', 0.2)}s_"""
        return md

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if self.enable_cors:
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        if self.enable_cors:
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def run(host='127.0.0.1', port=PORT, enable_cors=False):
    server = ThreadingHTTPServer((host, port), lambda *args, **kwargs: TriageRequestHandler(*args, enable_cors=enable_cors, **kwargs))
    print(f"🔥 Triage3AM Server running at http://{host}:{port}")
    print(f"📁 Serving static files from {STATIC_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Triage3AM Server')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=PORT, help='Port to bind to')
    parser.add_argument('--cors', action='store_true', help='Enable CORS')
    args = parser.parse_args()
    run(host=args.host, port=args.port, enable_cors=args.cors)