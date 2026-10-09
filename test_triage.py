"""
Unit and Integration Tests for Triage3AM.
Verifies Drain clustering, Patient Zero detection, impact scoring, and Slack export.
"""

import unittest
import os
import json
from triage_engine import TriageEngine
from server import TriageRequestHandler

class TestTriage3AM(unittest.TestCase):
    def setUp(self):
        self.engine = TriageEngine()
        self.ecommerce_log_path = 'datasets/ecommerce_cascade_10k.log'
        self.k8s_log_path = 'datasets/k8s_oom_cascade_10k.log'

    def test_ecommerce_scenario(self):
        self.assertTrue(os.path.exists(self.ecommerce_log_path))
        with open(self.ecommerce_log_path, 'r') as f:
            raw = f.read()
        
        report = self.engine.ingest_logs(raw)
        summary = report['summary']
        
        self.assertEqual(summary['total_lines_ingested'], 10000)
        self.assertGreater(summary['noise_reduction_percentage'], 99.0)
        self.assertIn('Database Connection Pool Starvation', summary['root_cause_summary'])
        self.assertIn('postgres-cluster', summary['services_impacted'])
        self.assertIn('order-service', summary['services_impacted'])
        
        # Verify top incident is P0
        p0 = report['incidents'][0]
        self.assertEqual(p0['priority'], 'P0')
        self.assertTrue(len(p0['diagnosis']['command']) > 0)

    def test_k8s_oom_scenario(self):
        self.assertTrue(os.path.exists(self.k8s_log_path))
        with open(self.k8s_log_path, 'r') as f:
            raw = f.read()

        report = self.engine.ingest_logs(raw)
        summary = report['summary']

        self.assertEqual(summary['total_lines_ingested'], 10000)
        self.assertGreater(summary['noise_reduction_percentage'], 99.0)
        self.assertIn('OOM', summary['root_cause_summary'])
        self.assertIn('auth-service', summary['services_impacted'])

    def test_redis_scenario(self):
        redis_path = 'datasets/redis_thundering_herd_10k.log'
        self.assertTrue(os.path.exists(redis_path))
        with open(redis_path, 'r') as f:
            raw = f.read()

        report = self.engine.ingest_logs(raw)
        summary = report['summary']

        self.assertEqual(summary['total_lines_ingested'], 10000)
        self.assertGreater(summary['noise_reduction_percentage'], 99.0)
        self.assertIn('redis-cluster', summary['services_impacted'])

    def test_v2_spike_and_topology(self):
        with open(self.ecommerce_log_path, 'r') as f:
            raw = f.read()
        report = self.engine.ingest_logs(raw)
        
        # Verify V2 histogram
        hist = report.get('error_histogram')
        self.assertIsNotNone(hist)
        self.assertIsNotNone(hist['spike_detected_at'])
        self.assertGreater(hist['peak_error_rate'], 0)

        # Verify V2 topology graph
        graph = report.get('service_graph')
        self.assertIsNotNone(graph)
        self.assertGreater(len(graph['nodes']), 0)
        self.assertGreater(len(graph['edges']), 0)

    def test_postmortem_generation(self):
        from triage_engine import export_postmortem_markdown
        with open(self.ecommerce_log_path, 'r') as f:
            raw = f.read()
        report = self.engine.ingest_logs(raw)
        pir_md = export_postmortem_markdown(report)
        self.assertIn('Post-Incident Review', pir_md)
        self.assertIn('Patient Zero', pir_md)
        self.assertIn('Triage3AM v2.0', pir_md)

if __name__ == '__main__':
    unittest.main()
