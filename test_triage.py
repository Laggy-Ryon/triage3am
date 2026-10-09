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

    def test_slack_markdown_generation(self):
        with open(self.ecommerce_log_path, 'r') as f:
            raw = f.read()
        report = self.engine.ingest_logs(raw)
        handler = TriageRequestHandler
        slack_md = handler._generate_slack_markdown(None, report)
        self.assertIn('INCIDENT ALERT', slack_md)
        self.assertIn('Root Cause Hypothesis', slack_md)
        self.assertIn('Patient Zero', slack_md)

if __name__ == '__main__':
    unittest.main()
