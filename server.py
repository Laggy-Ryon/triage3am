"""
Triage3AM Web Server (v2.0): High-concurrency threaded HTTP server with REST API,
streaming file ingestion, multipart upload support, dynamic dataset discovery,
and multi-format incident export.
"""

import os
import io
import time
import json
import gzip
import socket
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict, Any, Optional

from triage_engine import TriageEngine, export_postmortem_markdown
from file_handler import (
    SafePathManager,
    StreamingLogReader,
    MultipartFormDataParser,
    IncidentReportExporter,
    ArchiveManager,
    get_mime_type,
    MAX_UPLOAD_SIZE
)

PORT = 8000
SERVER_START_TIME = time.time()
HOST = os.environ.get('TRIAGE_HOST', '127.0.0.1')
MAX_REQUEST_BYTES = int(os.environ.get('TRIAGE_MAX_REQUEST_BYTES', MAX_UPLOAD_SIZE))
MAX_LOG_LINES = int(os.environ.get('TRIAGE_MAX_LOG_LINES', 100_000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
DATASETS_DIR = os.path.join(BASE_DIR, 'datasets')


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server preventing log ingestion from blocking concurrent requests."""
    daemon_threads = True
    allow_reuse_address = True


class TriageRequestHandler(SimpleHTTPRequestHandler):
    """High-performance request handler supporting v1 and v2 Triage3AM endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    # -------------------------------------------------------------
    # GET Endpoints
    # -------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Health checks (v1 & v2)
        if path in ('/api/health', '/api/v2/health'):
            uptime = round(time.time() - SERVER_START_TIME, 2)
            self._send_json({
                'status': 'ok',
                'server': 'Triage3AM v2.0',
                'version': '2.0.0',
                'uptime_seconds': uptime,
                'max_upload_size_mb': MAX_UPLOAD_SIZE // (1024 * 1024),
                'capabilities': [
                    'trie_drain_clustering',
                    'streaming_file_ingestion',
                    'multipart_upload',
                    'gzip_compression',
                    'dynamic_dataset_discovery',
                    'temporal_cascade_graph',
                    'error_rate_spike_histogram',
                    'service_blast_radius_topology'
                ]
            })

        # Presets discovery (v1 & v2)
        elif path in ('/api/presets', '/api/v2/presets'):
            self._handle_get_presets()

        # Load preset content (v1 & v2)
        elif path in ('/api/load-preset', '/api/v2/presets/load'):
            preset_name = query.get('name', [''])[0]
            limit_str = query.get('limit', [None])[0]
            offset_str = query.get('offset', ['0'])[0]
            limit = int(limit_str) if limit_str and limit_str.isdigit() else None
            offset = int(offset_str) if offset_str.isdigit() else 0
            self._handle_load_preset(preset_name, limit=limit, offset=offset)

        # Server metrics (v2)
        elif path == '/api/v2/metrics':
            self._handle_get_metrics()

        # Single file download (v1 & v2)
        elif path in ('/api/download', '/api/v2/download'):
            file_name = query.get('file', [''])[0] or query.get('name', [''])[0]
            self._handle_file_download(file_name)

        # Datasets bundle zip download (v2)
        elif path in ('/api/download-bundle', '/api/v2/download/bundle', '/api/v2/download-all'):
            self._handle_bundle_download()

        else:
            # Fallback to static file server with cache control
            super().do_GET()

    # -------------------------------------------------------------
    # POST Endpoints
    # -------------------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Validate Content-Length before reading into memory
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_UPLOAD_SIZE:
            self._send_error(
                f"Payload size ({content_length} bytes) exceeds server limit of {MAX_UPLOAD_SIZE} bytes (100MB).",
                status=413,
                code="PAYLOAD_TOO_LARGE"
            )
            return

        content_type = self.headers.get('Content-Type', '')

        # 1. Multipart File Upload Analysis (/api/upload or /api/v2/analyze/upload)
        if path in ('/api/upload', '/api/v2/analyze/upload'):
            self._handle_multipart_upload(content_type, content_length)

        # 2. Raw JSON or Text Log Analysis (/api/analyze or /api/v2/analyze)
        elif path in ('/api/analyze', '/api/v2/analyze'):
            self._handle_analyze_post(content_type, content_length)

        # 3. Export Reports (/api/export-slack, /api/export-postmortem, or /api/v2/export)
        elif path == '/api/export-slack':
            self._handle_export_slack_legacy(content_length)
        elif path == '/api/export-postmortem':
            self._handle_export_postmortem_legacy(content_length)
        elif path in ('/api/export', '/api/v2/export'):
            self._handle_export_v2(content_length)

        # 4. Direct Report File Download (/api/export/download or /api/v2/export/download)
        elif path in ('/api/export/download', '/api/v2/export/download'):
            self._handle_export_download(content_length)

        else:
            self._send_error(f"Endpoint '{path}' not found", status=404, code="NOT_FOUND")

    # -------------------------------------------------------------
    # Internal Request Processors
    # -------------------------------------------------------------
    def _handle_get_presets(self):
        """Scans presets dynamically from datasets directory."""
        try:
            presets = SafePathManager.scan_presets(DATASETS_DIR)
            self._send_json({'presets': presets, 'count': len(presets)})
        except Exception as e:
            self._send_error(f"Failed to scan presets: {str(e)}", status=500)

    def _handle_load_preset(self, name: str, limit: Optional[int] = None, offset: int = 0):
        """Loads a preset safely with optional pagination."""
        if not name:
            self._send_error("Missing 'name' query parameter", status=400, code="MISSING_PARAM")
            return

        target_path = SafePathManager.resolve_safe_path(DATASETS_DIR, name)
        if not target_path or not target_path.exists():
            self._send_error(f"Preset '{name}' not found", status=404, code="PRESET_NOT_FOUND")
            return

        try:
            lines = []
            for _, line in StreamingLogReader.stream_lines(target_path, max_lines=limit, offset=offset):
                lines.append(line)

            content = "\n".join(lines)
            self._send_json({
                'name': target_path.name,
                'lines_count': len(lines),
                'offset': offset,
                'limit': limit,
                'is_truncated': limit is not None,
                'content': content
            })
        except Exception as e:
            self._send_error(f"Failed reading preset: {str(e)}", status=500)

    def _handle_multipart_upload(self, content_type: str, content_length: int):
        """Processes multipart/form-data uploaded file and performs immediate triage."""
        try:
            parsed_data = MultipartFormDataParser.parse(
                self.rfile, content_type, content_length, max_size=MAX_UPLOAD_SIZE
            )

            files = parsed_data.get('files', {})
            if not files:
                self._send_error("No files provided in multipart upload", status=400, code="NO_FILE")
                return

            file_info = next(iter(files.values()))
            raw_text = file_info.get('content', '')
            filename = file_info.get('filename', 'uploaded_file.log')

            threshold_str = parsed_data.get('fields', {}).get('threshold', '0.55')
            try:
                threshold = float(threshold_str)
            except ValueError:
                threshold = 0.55

            engine = TriageEngine(similarity_threshold=threshold)
            report = engine.ingest_logs(raw_text)
            report['summary']['source_file'] = filename
            report['summary']['source_type'] = 'multipart_upload'

            self._send_json(report)
        except Exception as e:
            self._send_error(f"Multipart processing error: {str(e)}", status=500)

    def _handle_analyze_post(self, content_type: str, content_length: int):
        """Processes raw text or JSON body containing logs."""
        try:
            raw_body = self.rfile.read(content_length)

            if self.headers.get('Content-Encoding') == 'gzip':
                raw_body = gzip.decompress(raw_body)

            post_data = raw_body.decode('utf-8', errors='replace')
            threshold = 0.55

            if post_data.strip().startswith('{'):
                try:
                    body = json.loads(post_data)
                    raw_logs = body.get('logs', '')
                    if 'threshold' in body:
                        threshold = float(body.get('threshold', 0.55))
                except json.JSONDecodeError:
                    raw_logs = post_data
            else:
                raw_logs = post_data

            if not raw_logs.strip():
                self._send_error("Logs payload is empty", status=400, code="EMPTY_LOGS")
                return

            engine = TriageEngine(similarity_threshold=threshold)
            report = engine.ingest_logs(raw_logs)
            self._send_json(report)
        except Exception as e:
            self._send_error(f"Analysis engine error: {str(e)}", status=500)

    def _handle_export_slack_legacy(self, content_length: int):
        """v1 backward compatible Slack export endpoint."""
        try:
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            slack_msg = IncidentReportExporter.to_slack_markdown(data)
            self._send_json({'markdown': slack_msg})
        except Exception as e:
            self._send_error(str(e), status=500)

    def _handle_export_postmortem_legacy(self, content_length: int):
        """v2 Post-Incident Review export endpoint."""
        try:
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            pir_msg = IncidentReportExporter.to_incident_postmortem_markdown(data)
            self._send_json({'markdown': pir_msg})
        except Exception as e:
            self._send_error(str(e), status=500)

    def _handle_export_v2(self, content_length: int):
        """v2 multi-format export endpoint (slack, markdown, csv, json)."""
        try:
            post_data = self.rfile.read(content_length).decode('utf-8')
            payload = json.loads(post_data)
            fmt = payload.get('format', 'slack').lower()
            report = payload.get('report') or payload

            if fmt == 'slack':
                rendered = IncidentReportExporter.to_slack_markdown(report)
                self._send_json({'format': 'slack', 'content': rendered, 'content_type': 'text/markdown'})
            elif fmt in ('markdown', 'md', 'postmortem'):
                rendered = IncidentReportExporter.to_incident_postmortem_markdown(report)
                self._send_json({'format': 'markdown', 'content': rendered, 'content_type': 'text/markdown'})
            elif fmt == 'csv':
                rendered = IncidentReportExporter.to_csv_summary(report)
                self._send_json({'format': 'csv', 'content': rendered, 'content_type': 'text/csv'})
            elif fmt == 'json':
                rendered = json.dumps(report, indent=2)
                self._send_json({'format': 'json', 'content': rendered, 'content_type': 'application/json'})
            else:
                self._send_error(f"Unsupported format '{fmt}'. Choose slack, markdown, csv, or json.", status=400)
        except Exception as e:
            self._send_error(f"Export failed: {str(e)}", status=500)

    def _handle_get_metrics(self):
        """Returns runtime server metrics and environment details."""
        import threading
        uptime = round(time.time() - SERVER_START_TIME, 2)
        self._send_json({
            'status': 'healthy',
            'uptime_seconds': uptime,
            'active_threads': threading.active_count(),
            'port': PORT,
            'max_upload_size_bytes': MAX_UPLOAD_SIZE,
            'datasets_directory': DATASETS_DIR
        })

    def _handle_file_download(self, filename: str):
        """Safely streams an individual dataset file as an HTTP attachment download."""
        if not filename:
            self._send_error("Missing 'file' or 'name' parameter for download", status=400, code="MISSING_PARAM")
            return

        target_path = SafePathManager.resolve_safe_path(DATASETS_DIR, filename)
        if not target_path or not target_path.exists() or not target_path.is_file():
            self._send_error(f"File '{filename}' not found for download", status=404, code="FILE_NOT_FOUND")
            return

        try:
            file_size = target_path.stat().st_size
            mime_type = get_mime_type(target_path.name)

            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Length', str(file_size))
            self.send_header('Content-Disposition', f'attachment; filename="{target_path.name}"')
            self._set_cors_and_security_headers()
            self.end_headers()

            with open(target_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception as e:
            self._send_error(f"Failed streaming file download: {str(e)}", status=500)

    def _handle_bundle_download(self):
        """Creates an in-memory zip archive of all datasets and streams as download."""
        try:
            zip_buffer = io.BytesIO()
            file_count = ArchiveManager.create_zip_bundle(DATASETS_DIR, zip_buffer)
            zip_bytes = zip_buffer.getvalue()

            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', str(len(zip_bytes)))
            self.send_header('Content-Disposition', 'attachment; filename="triage3am_datasets.zip"')
            self._set_cors_and_security_headers()
            self.end_headers()
            self.wfile.write(zip_bytes)
        except Exception as e:
            self._send_error(f"Failed generating bundle archive: {str(e)}", status=500)

    def _handle_export_download(self, content_length: int):
        """Generates report and sends directly as file download attachment."""
        try:
            post_data = self.rfile.read(content_length).decode('utf-8')
            payload = json.loads(post_data)
            fmt = payload.get('format', 'markdown').lower()
            report = payload.get('report') or payload
            requested_name = payload.get('filename')

            if fmt == 'slack':
                content = IncidentReportExporter.to_slack_markdown(report).encode('utf-8')
                ext = 'txt'
                mime = 'text/plain; charset=utf-8'
            elif fmt in ('markdown', 'md', 'postmortem'):
                content = IncidentReportExporter.to_incident_postmortem_markdown(report).encode('utf-8')
                ext = 'md'
                mime = 'text/markdown; charset=utf-8'
            elif fmt == 'csv':
                content = IncidentReportExporter.to_csv_summary(report).encode('utf-8')
                ext = 'csv'
                mime = 'text/csv; charset=utf-8'
            elif fmt == 'json':
                content = json.dumps(report, indent=2).encode('utf-8')
                ext = 'json'
                mime = 'application/json; charset=utf-8'
            else:
                self._send_error(f"Unsupported format '{fmt}'. Choose slack, markdown, csv, or json.", status=400)
                return

            download_filename = requested_name or f"triage_incident_report_{int(time.time())}.{ext}"

            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Content-Disposition', f'attachment; filename="{download_filename}"')
            self._set_cors_and_security_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_error(f"Export download failed: {str(e)}", status=500)

    # -------------------------------------------------------------
    # Response Formatters & Headers
    # -------------------------------------------------------------
    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode('utf-8')
        accept_encoding = self.headers.get('Accept-Encoding', '')

        if len(body) > 1024 and 'gzip' in accept_encoding:
            body = gzip.compress(body)
            is_gzip = True
        else:
            is_gzip = False

        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        if is_gzip:
            self.send_header('Content-Encoding', 'gzip')
        self._set_cors_and_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400, code: str = "ERROR", details: Any = None):
        payload = {
            'error': message,
            'code': code,
            'status': status,
            'timestamp': time.time()
        }
        if details is not None:
            payload['details'] = details
        self._send_json(payload, status=status)

    def _set_cors_and_security_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, Content-Encoding')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_and_security_headers()
        self.send_header('Content-Length', '0')
        self.end_headers()

    @staticmethod
    def _generate_slack_markdown(handler_instance, report: dict) -> str:
        return IncidentReportExporter.to_slack_markdown(report)


def run(port=PORT):
    server = ThreadedHTTPServer(('0.0.0.0', port), TriageRequestHandler)
    print(f"🔥 Triage3AM v2.0 Server running at http://0.0.0.0:{port}")
    print(f"📁 Serving static files from {STATIC_DIR}")
    print(f"📦 Datasets directory: {DATASETS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()


if __name__ == '__main__':
    run()