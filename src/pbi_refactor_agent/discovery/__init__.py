"""Discovery module - Análise de dependências e impacto no modelo Power BI"""

from pbi_refactor_agent.discovery.dependency_graph import DependencyGraph
from pbi_refactor_agent.discovery.impact_analyzer import ImpactAnalyzer
from pbi_refactor_agent.discovery.model_health import ModelHealthAnalyzer
from pbi_refactor_agent.discovery.duplicate_detector import DuplicateDetector
from pbi_refactor_agent.discovery.risk_hotspots import RiskAnalyzer
from pbi_refactor_agent.discovery.production_validator import ProductionValidator
from pbi_refactor_agent.discovery.source_drift_detector import (
    analyze_source_drift,
    DriftSeverity,
    DriftType,
)

__all__ = [
    "DependencyGraph",
    "ImpactAnalyzer",
    "ModelHealthAnalyzer",
    "DuplicateDetector",
    "RiskAnalyzer",
    "ProductionValidator",
    "analyze_source_drift",
    "DriftSeverity",
    "DriftType",
]
