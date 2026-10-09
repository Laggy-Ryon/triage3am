"""
Unit and Integration Tests for Triage3AM (v2.0).
Verifies Drain clustering, Patient Zero detection, impact scoring, Slack export,
streaming file reading, multipart parsing, path safety, and gzip support.
"""

import os
import io
import gzip
import json
import unittest
from pathlib import Path

from triage_engine import TriageEngine
from server import TriageRequestHandler
from file_handler import (
    SafePathManager,
    StreamingLogReader,
    MultipartFormDataParser,
    IncidentReportExporter,
    MAX_UPLOAD_SIZE
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASETS_DIR = os.path.join(BASE_DIR, 'datasets')


class TestTriage3AM(unittest.TestCase):
    """v1 Backward-Compatibility Test Suite."""

    def setUp(self):
        self.engine = TriageEngine()
        self.ecommerce_log_path = os.path.join(DATASETS_DIR, 'ecommerce_cascade_10k.log')
        self.k8s_log_path = os.path.join(DATASETS_DIR, 'k8s_oom_cascade_10k.log')

    def test_ecommerce_scenario(self):
        self.assertTrue(os.path.exists(self.ecommerce_log_path), f"File not found: {self.ecommerce_log_path}")
        with open(self.ecommerce_log_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        report = self.engine.ingest_logs(raw)
        summary = report['summary']

        self.assertGreaterEqual(summary['total_lines_ingested'], 9999)
        self.assertGreater(summary['noise_reduction_percentage'], 99.0)
        self.assertIn('Database Connection Pool Starvation', summary['root_cause_summary'])
        self.assertIn('postgres-cluster', summary['services_impacted'])
        self.assertIn('order-service', summary['services_impacted'])

        # Verify top incident is P0
        p0 = report['incidents'][0]
        self.assertEqual(p0['priority'], 'P0')
        self.assertTrue(len(p0['diagnosis']['command']) > 0)

    def test_k8s_oom_scenario(self):
        self.assertTrue(os.path.exists(self.k8s_log_path), f"File not found: {self.k8s_log_path}")
        with open(self.k8s_log_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        report = self.engine.ingest_logs(raw)
        summary = report['summary']

        self.assertGreaterEqual(summary['total_lines_ingested'], 9999)
        self.assertGreater(summary['noise_reduction_percentage'], 99.0)
        self.assertIn('OOM', summary['root_cause_summary'])
        self.assertIn('auth-service', summary['services_impacted'])

    def test_slack_markdown_generation(self):
        with open(self.ecommerce_log_path, 'r', encoding='utf-8') as f:
            raw = f.read()
        report = self.engine.ingest_logs(raw)
        slack_md = TriageRequestHandler._generate_slack_markdown(None, report)
        self.assertIn('INCIDENT ALERT', slack_md)
        self.assertIn('Root Cause Hypothesis', slack_md)
        self.assertIn('Patient Zero', slack_md)


class TestTriageV2FileAndRequestHandling(unittest.TestCase):
    """v2 File & Request Handling Test Suite."""

    def setUp(self):
        self.datasets_dir = DATASETS_DIR
        self.engine = TriageEngine()

    def test_streaming_log_reader_memory_efficiency(self):
        """Verify stream_lines iteratively yields line pairs without in-memory buffering."""
        test_data = "line 1\nline 2\nline 3\nline 4\nline 5"
        streamed = list(StreamingLogReader.stream_lines(test_data))
        self.assertEqual(len(streamed), 5)
        self.assertEqual(streamed[0], (1, "line 1"))
        self.assertEqual(streamed[4], (5, "line 5"))

        # Test pagination (offset and limit)
        paginated = list(StreamingLogReader.stream_lines(test_data, max_lines=2, offset=1))
        self.assertEqual(len(paginated), 2)
        self.assertEqual(paginated[0], (2, "line 2"))
        self.assertEqual(paginated[1], (3, "line 3"))

    def test_streaming_gzip_file_reading(self):
        """Verify streaming decompression of .gz files directly from disk."""
        gz_path = os.path.join(self.datasets_dir, 'ecommerce_cascade_10k.log.gz')
        if not os.path.exists(gz_path):
            # Create if needed
            src = os.path.join(self.datasets_dir, 'ecommerce_cascade_10k.log')
            with open(src, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
                f_out.writelines(f_in)

        # Stream first 100 lines from gzip file
        streamed = list(StreamingLogReader.stream_lines(gz_path, max_lines=100))
        self.assertEqual(len(streamed), 100)
        self.assertTrue(len(streamed[0][1]) > 0)

    def test_safe_path_resolution(self):
        """Verify directory traversal attempts are strictly neutralized."""
        base = self.datasets_dir

        # Normal valid file
        valid = SafePathManager.resolve_safe_path(base, 'ecommerce_cascade_10k.log')
        self.assertIsNotNone(valid)
        self.assertTrue(valid.exists())

        # Directory traversal attacks
        self.assertIsNone(SafePathManager.resolve_safe_path(base, '../../etc/passwd'))
        self.assertIsNone(SafePathManager.resolve_safe_path(base, '/etc/passwd'))
        self.assertIsNone(SafePathManager.resolve_safe_path(base, '..%2f..%2fetc/passwd'))

    def test_dynamic_preset_discovery(self):
        """Verify dynamic scanning detects all log files and computes metadata."""
        presets = SafePathManager.scan_presets(self.datasets_dir)
        self.assertGreaterEqual(len(presets), 3)

        preset_ids = [p['id'] for p in presets]
        self.assertIn('ecommerce_cascade_10k.log', preset_ids)
        self.assertIn('k8s_oom_cascade_10k.log', preset_ids)
        self.assertIn('redis_stampede_10k.log', preset_ids)

        for p in presets:
            self.assertIn('title', p)
            self.assertIn('size_formatted', p)
            self.assertIn('lines', p)
            self.assertGreater(p['lines'], 0)

    def test_multipart_form_parser(self):
        """Verify pure Python multipart/form-data parser correctly parses uploaded files."""
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        content_type = f"multipart/form-data; boundary={boundary}"

        file_content = "2026-10-10T03:00:00Z [auth-service] ERROR Token expired\n2026-10-10T03:00:01Z [auth-service] INFO Retry ok"
        multipart_payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="threshold"\r\n\r\n'
            f"0.65\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="auth.log"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"{file_content}\r\n"
            f"--{boundary}--\r\n"
        ).encode('utf-8')

        stream = io.BytesIO(multipart_payload)
        parsed = MultipartFormDataParser.parse(stream, content_type, len(multipart_payload))

        self.assertEqual(parsed['fields'].get('threshold'), '0.65')
        self.assertIn('file', parsed['files'])
        self.assertEqual(parsed['files']['file']['filename'], 'auth.log')
        self.assertEqual(parsed['files']['file']['content'], file_content)

    def test_redis_cache_stampede_scenario(self):
        """Verify scenario 3 (Redis cache eviction) correctly identifies root cause."""
        redis_log_path = os.path.join(self.datasets_dir, 'redis_stampede_10k.log')
        self.assertTrue(os.path.exists(redis_log_path))

        with open(redis_log_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        report = self.engine.ingest_logs(raw)
        self.assertIn('Cache Layer Saturation', report['summary']['root_cause_summary'])
        self.assertIn('redis-cluster', report['summary']['services_impacted'])

    def test_multiformat_export_reporters(self):
        """Verify all export formatters (Slack, Markdown Postmortem, CSV)."""
        redis_log_path = os.path.join(self.datasets_dir, 'redis_stampede_10k.log')
        with open(redis_log_path, 'r', encoding='utf-8') as f:
            raw = f.read()
        report = self.engine.ingest_logs(raw)

        # Slack
        slack_out = IncidentReportExporter.to_slack_markdown(report)
        self.assertIn('INCIDENT ALERT', slack_out)

        # Markdown Post-Mortem
        md_out = IncidentReportExporter.to_incident_postmortem_markdown(report)
        self.assertIn('# Incident Post-Mortem', md_out)
        self.assertIn('## 1. Executive Summary', md_out)
        self.assertIn('## 2. Patient Zero Anomaly', md_out)
        self.assertIn('## 4. Cascading Failure Chain', md_out)

        # CSV Summary
        csv_out = IncidentReportExporter.to_csv_summary(report)
        self.assertIn('Rank,ID,Priority,Service', csv_out)
        self.assertIn('P0', csv_out)


if __name__ == '__main__':
    unittest.main()
