"""
FinOps Module - Tag-Centric Cost Management with AWS CUR Integration.

This module provides comprehensive cost analysis, chargeback reporting,
anomaly detection, and visibility gap analysis using AWS Cost and Usage
Reports (CUR) via Athena, with Cost Explorer API fallback.

Key Features:
- CUR auto-detection and bluearch-core-managed setup
- Tag-based chargeback reports with multi-dimensional grouping
- Untagged resource cost analysis (visibility gaps)
- Cost anomaly detection with configurable thresholds
- Historical cost trends by tag dimension
"""

from .cur_client import CURClient, CostDataSource
from .cur_setup import CURSetup, CURConfiguration as CURConfigResult
from .chargeback import ChargebackReporter, ChargebackReport
from .visibility_gaps import VisibilityGapAnalyzer, GapReport
from .anomaly_detector import AnomalyDetector, CostAnomaly
from .cost_trends import TrendAnalyzer, TrendReport

__all__ = [
    # CUR Integration
    'CURClient',
    'CostDataSource',
    'CURSetup',
    'CURConfigResult',
    # Chargeback
    'ChargebackReporter',
    'ChargebackReport',
    # Visibility Gaps
    'VisibilityGapAnalyzer',
    'GapReport',
    # Anomaly Detection
    'AnomalyDetector',
    'CostAnomaly',
    # Trends
    'TrendAnalyzer',
    'TrendReport',
]

__version__ = '1.0.0'
