"""
Hotspots de Risco do Modelo Semantico.

Simula o impacto de renomear cada coluna/tabela do modelo para
identificar os objetos mais criticos — aqueles cuja mudanca
afetaria o maior numero de expressoes DAX.
"""

from dataclasses import dataclass, field
from typing import Optional

import structlog

from pbi_refactor_agent.models import ChangeType, ProposedChange

logger = structlog.get_logger(__name__)


@dataclass
class RiskHotspot:
    """Um objeto com alto risco de impacto."""
    object_type: str  # "column" ou "table"
    table_name: str
    object_name: str
    total_impacted: int
    direct_impacts: int
    cascade_impacts: int
    relationship_impacts: int

    @property
    def full_name(self) -> str:
        if self.object_type == "column":
            return f"{self.table_name}[{self.object_name}]"
        return self.table_name

    @property
    def risk_level(self) -> str:
        if self.total_impacted >= 10:
            return "critical"
        if self.total_impacted >= 5:
            return "high"
        if self.total_impacted >= 2:
            return "medium"
        return "low"


@dataclass
class RiskReport:
    """Relatorio de hotspots de risco."""
    hotspots: list[RiskHotspot] = field(default_factory=list)
    total_objects_analyzed: int = 0

    @property
    def top_hotspots(self) -> list[RiskHotspot]:
        """Top 10 objetos mais arriscados."""
        return sorted(self.hotspots, key=lambda h: h.total_impacted, reverse=True)[:10]

    @property
    def critical_count(self) -> int:
        return sum(1 for h in self.hotspots if h.risk_level == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for h in self.hotspots if h.risk_level == "high")


class RiskAnalyzer:
    """
    Analisa hotspots de risco simulando o impacto de cada objeto.

    Para cada coluna e tabela do modelo, simula um renomeio e
    conta quantos objetos seriam afetados.
    """

    def __init__(self, graph, analyzer):
        """
        Args:
            graph: DependencyGraph populado.
            analyzer: ImpactAnalyzer instanciado.
        """
        self._graph = graph
        self._analyzer = analyzer

    def analyze(self, metadata) -> RiskReport:
        """
        Simula impacto para cada coluna e tabela do modelo.

        Args:
            metadata: ModelMetadata extraido do .pbit.

        Returns:
            RiskReport com ranking de hotspots.
        """
        report = RiskReport()

        for table in metadata.business_tables:
            # Simula renomeio da tabela
            report.total_objects_analyzed += 1
            try:
                change = ProposedChange(
                    change_type=ChangeType.RENAME_TABLE,
                    table_name=None,
                    object_name=table.name,
                    new_value=f"{table.name}_SIMULATED",
                )
                impact = self._analyzer.analyze(change)
                if impact.total_impacted > 0:
                    report.hotspots.append(RiskHotspot(
                        object_type="table",
                        table_name=table.name,
                        object_name=table.name,
                        total_impacted=impact.total_impacted,
                        direct_impacts=len(impact.direct_impacts),
                        cascade_impacts=len(impact.cascade_impacts),
                        relationship_impacts=len(impact.relationship_impacts),
                    ))
            except Exception:
                pass

            # Simula renomeio de cada coluna
            for col in table.columns:
                report.total_objects_analyzed += 1
                try:
                    change = ProposedChange(
                        change_type=ChangeType.RENAME_COLUMN,
                        table_name=table.name,
                        object_name=col.name,
                        new_value=f"{col.name}_SIMULATED",
                    )
                    impact = self._analyzer.analyze(change)
                    if impact.total_impacted > 0:
                        report.hotspots.append(RiskHotspot(
                            object_type="column",
                            table_name=table.name,
                            object_name=col.name,
                            total_impacted=impact.total_impacted,
                            direct_impacts=len(impact.direct_impacts),
                            cascade_impacts=len(impact.cascade_impacts),
                            relationship_impacts=len(impact.relationship_impacts),
                        ))
                except Exception:
                    pass

        report.hotspots.sort(key=lambda h: h.total_impacted, reverse=True)

        logger.info(
            "Analise de hotspots concluida",
            objects_analyzed=report.total_objects_analyzed,
            hotspots_found=len(report.hotspots),
            critical=report.critical_count,
        )
        return report
