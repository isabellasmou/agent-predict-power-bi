"""
PBI Refactor Agent
Agente para Análise Preditiva de Impacto e Refatoração Semiautomática 
de Modelos Semânticos Power BI com LLM e MCP

TCC - Isabella da Silva Moura - FAETERJ 2026
"""

__version__ = "1.0.0"

from pbi_refactor_agent.agent import RefactorAgent
from pbi_refactor_agent.models import (
    ChangeType,
    ProposedChange,
    ImpactAnalysis,
    RefactorResult,
    SyntaxValidation,
)
from pbi_refactor_agent.config import LLMProvider, Settings, get_settings

__all__ = [
    "RefactorAgent",
    "ChangeType",
    "ProposedChange",
    "ImpactAnalysis",
    "RefactorResult",
    "SyntaxValidation",
    "LLMProvider",
    "Settings",
    "get_settings",
    "__version__",
]
