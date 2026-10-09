"""
In-process Mock HTTP Request Handler Tests for Triage3AM v2 Server.
Tests request dispatching, headers, status codes, query strings, multipart,
and JSON responses using in-memory streams without opening network sockets.
"""

import io
import os
import json
import unittest
from unittest.mock import MagicMock

from server import TriageRequestHandler, DATASETS_DIR
from file_handler import SafePathManager


class DummyServer:
    pass


class MockHTTPConnection:
    def __init__(self, request_bytes: bytes):
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        if 'b' in mode:
            if 'w' in mode:
                return self.wfile
            return self.rfile
        return io.TextIOWrapper(self.rfile)

    def sendall(self, data):
        self.wfile.write(data)


class ParsedResponse:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.status_code = 0
        self.headers = {}
        self.body_bytes = b''
        self.body_text = ''
        self.json = None
        self._parse()

    def _parse(self):
        parts = self.raw.split(b'\r\n\r\n', 1)
        if not parts:
            return
        header_part = parts[0].decode('utf-8', errors='replace')
        if len(parts) > 1:
            self.body_bytes = parts[1]
            self.body_text = self.body_bytes.decode('utf-8', errors='replace')
            try:
                self.json = json.loads(self.body_text)
            except Exception:
                self.json = None

        lines = header_part.split('\r\n')
        if lines:
            status_line = lines[0]
            status_tokens = status_line.split()
            if len(status_tokens) >= 2 and status_tokens[1].isdigit():
                self.status_code = int(status_tokens[1])

        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                self.headers[k.strip().lower()] = v.strip()


def execute_mock_request(request_raw: bytes) -> ParsedResponse:
    """Invokes TriageRequestHandler directly with an in-memory stream."""
    sock = MockHTTPConnection(request_raw)
    server = DummyServer()
    # TriageRequestHandler.__init__ calls handle() which parses request and executes do_GET / do_POST
    handler = TriageRequestHandler(sock, ('127.0.0.1', 54321), server)
    response_bytes = sock.wfile.getvalue()
    return ParsedResponse(response_bytes)


class TestTriageRequestHandlerInProcess(unittest.TestCase):
    def test_get_health_v1_and_v2(self):
        req = b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.json)
        self.assertEqual(resp.json['status'], 'ok')
        self.assertEqual(resp.json['server'], 'Triage3AM v2.0')

        req2 = b"GET /api/v2/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp2 = execute_mock_request(req2)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json['version'], '2.0.0')
        self.assertIn('trie_drain_clustering', resp2.json['capabilities'])

    def test_get_metrics(self):
        req = b"GET /api/v2/metrics HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json['status'], 'healthy')
        self.assertIn('uptime_seconds', resp.json)

    def test_get_presets(self):
        req = b"GET /api/v2/presets HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json['count'], 2)
        self.assertIn('presets', resp.json)

    def test_load_preset_with_limit(self):
        req = b"GET /api/load-preset?name=ecommerce_cascade_10k.log&limit=10 HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json['name'], 'ecommerce_cascade_10k.log')
        self.assertEqual(resp.json['lines_count'], 10)
        self.assertTrue(resp.json['is_truncated'])

    def test_load_preset_missing_param_and_not_found(self):
        # Missing name param
        req = b"GET /api/load-preset HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json['code'], 'MISSING_PARAM')

        # Traversal / Not found
        req2 = b"GET /api/load-preset?name=../../etc/passwd HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp2 = execute_mock_request(req2)
        self.assertEqual(resp2.status_code, 404)

    def test_post_analyze_json(self):
        body = json.dumps({
            'logs': (
                "2026-10-10T03:00:00Z [auth-service] INFO Started server\n"
                "2026-10-10T03:02:11Z [postgres-cluster] FATAL remaining connection slots are reserved (max_connections=100)\n"
                "2026-10-10T03:02:12Z [order-service] ERROR HikariPool-1 - Connection is not available\n"
            ),
            'threshold': 0.55
        }).encode('utf-8')

        req = (
            b"POST /api/v2/analyze HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode('utf-8')
            + body
        )
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json['summary']['total_lines_ingested'], 3)
        self.assertEqual(resp.json['incidents'][0]['priority'], 'P0')

    def test_post_multipart_upload(self):
        boundary = "BoundaryXYZ123"
        content_type = f"multipart/form-data; boundary={boundary}"
        payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="auth_test.log"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"2026-10-10T03:14:52 [auth-service] CRITICAL java.lang.OutOfMemoryError: Java heap space\r\n"
            f"--{boundary}--\r\n"
        ).encode('utf-8')

        req = (
            b"POST /api/v2/analyze/upload HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            + f"Content-Type: {content_type}\r\n".encode('utf-8')
            + f"Content-Length: {len(payload)}\r\n\r\n".encode('utf-8')
            + payload
        )
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json['summary']['source_file'], 'auth_test.log')
        self.assertEqual(resp.json['summary']['source_type'], 'multipart_upload')
        self.assertIn('OOM', resp.json['summary']['root_cause_summary'])

    def test_post_export_formats(self):
        report = {
            'summary': {
                'total_lines_ingested': 5000,
                'actionable_incidents': 1,
                'noise_reduction_percentage': 99.8,
                'outage_started_at': '03:02:11 UTC',
                'root_cause_summary': 'Database Connection Pool Starvation',
                'services_impacted': ['postgres-cluster']
            },
            'incidents': [{
                'rank': 1, 'priority': 'P0', 'primary_service': 'postgres-cluster',
                'line_count': 100, 'percentage_of_total': 2.0, 'first_seen': '03:02:11',
                'template': 'FATAL remaining slots <*> pid=<NUM>',
                'patient_zero': {'line_no': 10, 'service': 'postgres-cluster', 'raw': 'FATAL slots full'},
                'diagnosis': {'root_cause': 'Database Connection Pool Starvation', 'command': 'kubectl scale db-pool'}
            }],
            'cascade_chain': []
        }

        # Test Markdown Export
        body_md = json.dumps({'format': 'markdown', 'report': report}).encode('utf-8')
        req_md = (
            b"POST /api/v2/export HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body_md)}\r\n\r\n".encode('utf-8')
            + body_md
        )
        resp_md = execute_mock_request(req_md)
        self.assertEqual(resp_md.status_code, 200)
        self.assertEqual(resp_md.json['format'], 'markdown')
        self.assertIn('# Incident Post-Mortem', resp_md.json['content'])

        # Test CSV Export
        body_csv = json.dumps({'format': 'csv', 'report': report}).encode('utf-8')
        req_csv = (
            b"POST /api/v2/export HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body_csv)}\r\n\r\n".encode('utf-8')
            + body_csv
        )
        resp_csv = execute_mock_request(req_csv)
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv.json['format'], 'csv')
        self.assertIn('Rank,ID,Priority,Service', resp_csv.json['content'])

    def test_payload_too_large(self):
        req = (
            b"POST /api/v2/analyze HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {150 * 1024 * 1024}\r\n\r\n".encode('utf-8')
        )
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json['code'], 'PAYLOAD_TOO_LARGE')

    def test_download_dataset_file(self):
        req = b"GET /api/v2/download?file=ecommerce_cascade_10k.log HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('content-type'), 'text/plain; charset=utf-8')
        self.assertIn('attachment', resp.headers.get('content-disposition', ''))
        self.assertIn('ecommerce_cascade_10k.log', resp.headers.get('content-disposition', ''))
        self.assertGreater(len(resp.body_bytes), 1000)

    def test_download_gzip_dataset_file(self):
        req = b"GET /api/v2/download?file=ecommerce_cascade_10k.log.gz HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('content-type'), 'application/gzip')
        self.assertIn('attachment', resp.headers.get('content-disposition', ''))
        # Check gzip magic header bytes
        self.assertEqual(resp.body_bytes[:2], b'\x1f\x8b')

    def test_download_path_traversal_blocked(self):
        req = b"GET /api/v2/download?file=../../etc/passwd HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 404)

        req_empty = b"GET /api/v2/download HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp_empty = execute_mock_request(req_empty)
        self.assertEqual(resp_empty.status_code, 400)

    def test_download_bundle_zip(self):
        import zipfile
        req = b"GET /api/v2/download/bundle HTTP/1.1\r\nHost: localhost\r\n\r\n"
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('content-type'), 'application/zip')
        self.assertIn('attachment', resp.headers.get('content-disposition', ''))
        self.assertIn('triage3am_datasets.zip', resp.headers.get('content-disposition', ''))

        # Verify it is a valid zip archive and contains datasets
        zf = zipfile.ZipFile(io.BytesIO(resp.body_bytes))
        namelist = zf.namelist()
        self.assertIn('ecommerce_cascade_10k.log', namelist)
        self.assertIn('k8s_oom_cascade_10k.log', namelist)

    def test_post_export_download(self):
        report = {
            'summary': {
                'total_lines_ingested': 1000,
                'actionable_incidents': 1,
                'noise_reduction_percentage': 99.0,
                'outage_started_at': '03:02:11 UTC',
                'root_cause_summary': 'DB Starvation'
            },
            'incidents': [{
                'rank': 1, 'priority': 'P0', 'primary_service': 'postgres',
                'line_count': 10, 'percentage_of_total': 1.0, 'first_seen': '03:02:11',
                'template': 'FATAL <*> slots full',
                'patient_zero': {'line_no': 1, 'service': 'postgres', 'raw': 'FATAL slots full'},
                'diagnosis': {'root_cause': 'DB Starvation', 'command': 'kubectl scale db'}
            }],
            'cascade_chain': []
        }
        body = json.dumps({'format': 'markdown', 'report': report, 'filename': 'postmortem.md'}).encode('utf-8')
        req = (
            b"POST /api/v2/export/download HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode('utf-8')
            + body
        )
        resp = execute_mock_request(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('content-type'), 'text/markdown; charset=utf-8')
        self.assertIn('attachment', resp.headers.get('content-disposition', ''))
        self.assertIn('postmortem.md', resp.headers.get('content-disposition', ''))
        self.assertIn('# Incident Post-Mortem', resp.body_text)


if __name__ == '__main__':
    unittest.main()
