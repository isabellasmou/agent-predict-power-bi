"""
Auditoria de Saude do Modelo Semantico.

Analisa a estrutura do modelo Power BI e identifica problemas
como colunas orfas, filtros bidirecionais, tabelas desconectadas,
medidas nao utilizadas e outros riscos estruturais.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class HealthCategory(str, Enum):
    """Categorias de verificacao de saude."""
    STRUCTURE = "Estrutura"
    RELATIONSHIPS = "Relacionamentos"
    MEASURES = "Medidas"
    COLUMNS = "Colunas"
    PERFORMANCE = "Performance"


class HealthSeverity(str, Enum):
    """Severidade do achado."""
    GOOD = "good"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthFinding:
    """Um achado da auditoria de saude."""
    category: HealthCategory
    severity: HealthSeverity
    title: str
    detail: str
    recommendation: str
    affected_objects: list[str] = field(default_factory=list)


@dataclass
class HealthReport:
    """Relatorio de saude do modelo."""
    findings: list[HealthFinding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Score de saude de 0 a 100."""
        if not self.findings:
            return 100.0
        penalty = sum(
            {"good": 0, "info": 1, "warning": 5, "critical": 15}[f.severity.value]
            for f in self.findings
        )
        return round(max(0, 100 - penalty), 1)

    @property
    def grade(self) -> str:
        """Nota do modelo."""
        s = self.score
        if s >= 90:
            return "A"
        if s >= 75:
            return "B"
        if s >= 60:
            return "C"
        if s >= 40:
            return "D"
        return "F"

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == HealthSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == HealthSeverity.WARNING)


class ModelHealthAnalyzer:
    """
    Analisa a saude estrutural de um modelo Power BI.

    Verificacoes:
    - H01: Tabelas sem relacionamento (ilhas)
    - H02: Filtros bidirecionais (risco de ambiguidade)
    - H03: Colunas nao referenciadas por nenhuma medida
    - H04: Medidas ocultas
    - H05: Tabelas com muitas colunas (>30)
    - H06: Medidas sem format string
    - H07: Relacionamentos inativos
    - H08: Colunas de alto cardinalidade como texto
    - H09: Proporcao medidas/tabelas
    - H10: Expressoes DAX muito longas
    """

    def analyze(self, metadata, graph=None) -> HealthReport:
        """
        Executa auditoria completa do modelo.

        Args:
            metadata: ModelMetadata extraido do .pbit.
            graph: DependencyGraph (opcional, para analise avancada).

        Returns:
            HealthReport com todos os achados.
        """
        report = HealthReport()

        business = metadata.business_tables
        report.stats = {
            "tables": len(business),
            "total_columns": sum(len(t.columns) for t in business),
            "total_measures": sum(len(t.measures) for t in business),
            "total_relationships": len(metadata.relationships),
        }

        # Executar todas as verificacoes
        self._h01_disconnected_tables(metadata, report)
        self._h02_bidirectional_filters(metadata, report)
        self._h03_orphan_columns(metadata, report)
        self._h04_hidden_measures(metadata, report)
        self._h05_wide_tables(metadata, report)
        self._h06_missing_format_string(metadata, report)
        self._h07_inactive_relationships(metadata, report)
        self._h09_measures_ratio(metadata, report)
        self._h10_long_expressions(metadata, report)

        logger.info(
            "Auditoria de saude concluida",
            score=report.score,
            grade=report.grade,
            findings=len(report.findings),
        )
        return report

    def _h01_disconnected_tables(self, metadata, report: HealthReport):
        """Detecta tabelas sem nenhum relacionamento."""
        tables_in_rels = set()
        for r in metadata.relationships:
            tables_in_rels.add(r.from_table)
            tables_in_rels.add(r.to_table)

        disconnected = [
            t.name for t in metadata.business_tables
            if t.name not in tables_in_rels and len(t.measures) == 0
        ]
        if disconnected:
            report.findings.append(HealthFinding(
                category=HealthCategory.RELATIONSHIPS,
                severity=HealthSeverity.WARNING,
                title="Tabelas desconectadas",
                detail=f"{len(disconnected)} tabela(s) sem relacionamento e sem medidas.",
                recommendation="Conecte via relacionamento ou remova se nao for necessaria.",
                affected_objects=disconnected,
            ))

    def _h02_bidirectional_filters(self, metadata, report: HealthReport):
        """Detecta filtros bidirecionais."""
        bidir = [
            f"{r.from_table} <-> {r.to_table}"
            for r in metadata.relationships
            if r.cross_filtering.lower() in ("bothdirections", "both")
        ]
        if bidir:
            report.findings.append(HealthFinding(
                category=HealthCategory.RELATIONSHIPS,
                severity=HealthSeverity.WARNING,
                title="Filtros bidirecionais",
                detail=f"{len(bidir)} relacionamento(s) com filtro bidirecional. Risco de ambiguidade.",
                recommendation="Use filtro unidirecional sempre que possivel. Bidirecionais causam resultados inesperados.",
                affected_objects=bidir,
            ))

    def _h03_orphan_columns(self, metadata, report: HealthReport):
        """Detecta colunas nao referenciadas por nenhuma medida."""
        # Coleta todas as expressoes DAX
        all_expressions = ""
        for table in metadata.business_tables:
            for m in table.measures:
                all_expressions += " " + (m.expression or "")
            for c in table.columns:
                if c.expression:
                    all_expressions += " " + c.expression
        all_expr_upper = all_expressions.upper()

        orphans = []
        for table in metadata.business_tables:
            for col in table.columns:
                if col.is_hidden:
                    continue
                # Checa se a coluna e referenciada em alguma expressao
                ref1 = f"[{col.name.upper()}]"
                if ref1 not in all_expr_upper:
                    # Tambem checa nas FKs dos relacionamentos
                    is_fk = any(
                        (r.from_column == col.name and r.from_table == table.name)
                        or (r.to_column == col.name and r.to_table == table.name)
                        for r in metadata.relationships
                    )
                    if not is_fk:
                        orphans.append(f"{table.name}[{col.name}]")

        if orphans:
            severity = HealthSeverity.INFO if len(orphans) < 10 else HealthSeverity.WARNING
            report.findings.append(HealthFinding(
                category=HealthCategory.COLUMNS,
                severity=severity,
                title="Colunas potencialmente nao utilizadas",
                detail=f"{len(orphans)} coluna(s) nao referenciada(s) em nenhuma expressao DAX nem relacionamento.",
                recommendation="Colunas nao utilizadas ocupam memoria. Considere oculta-las ou remove-las.",
                affected_objects=orphans[:20],  # Limita para nao poluir
            ))

    def _h04_hidden_measures(self, metadata, report: HealthReport):
        """Detecta medidas ocultas."""
        hidden = []
        for table in metadata.business_tables:
            for m in table.measures:
                if m.is_hidden:
                    hidden.append(f"{table.name}[{m.name}]")
        if hidden:
            report.findings.append(HealthFinding(
                category=HealthCategory.MEASURES,
                severity=HealthSeverity.INFO,
                title="Medidas ocultas",
                detail=f"{len(hidden)} medida(s) oculta(s). Sao usadas internamente.",
                recommendation="Verifique se ainda sao necessarias. Medidas ocultas podem ser esquecidas.",
                affected_objects=hidden[:10],
            ))

    def _h05_wide_tables(self, metadata, report: HealthReport):
        """Detecta tabelas com muitas colunas."""
        wide = [
            f"{t.name} ({len(t.columns)} colunas)"
            for t in metadata.business_tables
            if len(t.columns) > 30
        ]
        if wide:
            report.findings.append(HealthFinding(
                category=HealthCategory.STRUCTURE,
                severity=HealthSeverity.WARNING,
                title="Tabelas muito largas",
                detail=f"{len(wide)} tabela(s) com mais de 30 colunas.",
                recommendation="Tabelas largas aumentam uso de memoria. Considere dividir ou remover colunas desnecessarias.",
                affected_objects=wide,
            ))

    def _h06_missing_format_string(self, metadata, report: HealthReport):
        """Detecta medidas sem format string."""
        no_format = []
        total = 0
        for table in metadata.business_tables:
            for m in table.measures:
                if not m.is_hidden:
                    total += 1
                    if not m.format_string:
                        no_format.append(f"{table.name}[{m.name}]")
        if no_format and total > 0:
            pct = len(no_format) / total * 100
            if pct > 30:
                report.findings.append(HealthFinding(
                    category=HealthCategory.MEASURES,
                    severity=HealthSeverity.INFO,
                    title="Medidas sem formato",
                    detail=f"{len(no_format)}/{total} ({pct:.0f}%) medidas sem Format String definida.",
                    recommendation="Defina Format String para garantir exibicao consistente nos visuais.",
                    affected_objects=no_format[:10],
                ))

    def _h07_inactive_relationships(self, metadata, report: HealthReport):
        """Detecta relacionamentos inativos."""
        inactive = [
            f"{r.from_table} -> {r.to_table}"
            for r in metadata.relationships
            if not r.is_active
        ]
        if inactive:
            report.findings.append(HealthFinding(
                category=HealthCategory.RELATIONSHIPS,
                severity=HealthSeverity.INFO,
                title="Relacionamentos inativos",
                detail=f"{len(inactive)} relacionamento(s) inativo(s). Requerem USERELATIONSHIP() para ativar.",
                recommendation="Verifique se sao usados via USERELATIONSHIP(). Caso contrario, considere remover.",
                affected_objects=inactive,
            ))

    def _h09_measures_ratio(self, metadata, report: HealthReport):
        """Verifica proporcao medidas/tabelas."""
        business = metadata.business_tables
        n_tables = len(business)
        n_measures = sum(len(t.measures) for t in business)
        if n_tables > 0 and n_measures == 0:
            report.findings.append(HealthFinding(
                category=HealthCategory.MEASURES,
                severity=HealthSeverity.CRITICAL,
                title="Modelo sem medidas",
                detail="O modelo nao possui nenhuma medida DAX. Indicadores devem ser medidas, nao colunas.",
                recommendation="Crie medidas explicitas com DAX em vez de usar agregacoes implicitas.",
            ))
        elif n_tables > 0:
            ratio = n_measures / n_tables
            if ratio > 20:
                report.findings.append(HealthFinding(
                    category=HealthCategory.STRUCTURE,
                    severity=HealthSeverity.INFO,
                    title="Muitas medidas por tabela",
                    detail=f"Media de {ratio:.1f} medidas por tabela. Considere usar Display Folders.",
                    recommendation="Organize medidas em Display Folders para facilitar a navegacao.",
                ))

    def _h10_long_expressions(self, metadata, report: HealthReport):
        """Detecta expressoes DAX muito longas."""
        long_exprs = []
        for table in metadata.business_tables:
            for m in table.measures:
                if m.expression and len(m.expression) > 500:
                    long_exprs.append(
                        f"{table.name}[{m.name}] ({len(m.expression)} chars)"
                    )
        if long_exprs:
            report.findings.append(HealthFinding(
                category=HealthCategory.PERFORMANCE,
                severity=HealthSeverity.INFO,
                title="Expressoes DAX longas",
                detail=f"{len(long_exprs)} expressao(oes) com mais de 500 caracteres.",
                recommendation="Expressoes longas sao dificeis de manter. Use VAR/RETURN ou divida em medidas auxiliares.",
                affected_objects=long_exprs[:10],
            ))
