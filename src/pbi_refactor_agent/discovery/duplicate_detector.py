"""
Detector de Medidas Duplicadas.

Compara expressoes DAX normalizadas para encontrar medidas que sao
identicas ou muito similares, indicando duplicacao no modelo.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DuplicateGroup:
    """Grupo de medidas duplicadas ou similares."""
    canonical_expression: str
    measures: list[tuple[str, str]] = field(default_factory=list)  # (table, measure)
    similarity: float = 1.0  # 1.0 = identicas

    @property
    def count(self) -> int:
        return len(self.measures)

    @property
    def names(self) -> list[str]:
        return [f"{t}[{m}]" for t, m in self.measures]


@dataclass
class DuplicateReport:
    """Relatorio de medidas duplicadas."""
    groups: list[DuplicateGroup] = field(default_factory=list)
    total_measures_analyzed: int = 0

    @property
    def total_duplicates(self) -> int:
        """Total de medidas duplicadas (excluindo a original de cada grupo)."""
        return sum(g.count - 1 for g in self.groups)

    @property
    def wasted_measures(self) -> int:
        """Medidas que poderiam ser eliminadas."""
        return self.total_duplicates


class DuplicateDetector:
    """
    Detecta medidas com expressoes DAX identicas ou muito similares.

    Normalizacao aplicada:
    - Remove espacos e quebras de linha
    - Converte para minusculas
    - Remove comentarios
    - Normaliza aspas
    """

    def analyze(self, metadata) -> DuplicateReport:
        """
        Analisa todas as medidas do modelo em busca de duplicatas.

        Args:
            metadata: ModelMetadata extraido do .pbit.

        Returns:
            DuplicateReport com os grupos de duplicatas.
        """
        report = DuplicateReport()

        # Coletar todas as medidas com expressoes
        measures = []
        for table in metadata.business_tables:
            for m in table.measures:
                if m.expression and m.expression.strip():
                    measures.append((table.name, m.name, m.expression))

        report.total_measures_analyzed = len(measures)

        # Agrupar por expressao normalizada
        normalized_groups: dict[str, list[tuple[str, str, str]]] = {}
        for tname, mname, expr in measures:
            norm = self._normalize(expr)
            normalized_groups.setdefault(norm, []).append((tname, mname, expr))

        # Encontrar grupos com duplicatas
        for norm_expr, group in normalized_groups.items():
            if len(group) >= 2:
                dg = DuplicateGroup(
                    canonical_expression=group[0][2][:200],  # expressao original
                    measures=[(t, m) for t, m, _ in group],
                    similarity=1.0,
                )
                report.groups.append(dg)

        # Busca de similaridade parcial (medidas quase iguais)
        # Comparacao simplificada: mesma estrutura, nomes diferentes
        norms = list(normalized_groups.keys())
        checked = set()
        for i, norm_a in enumerate(norms):
            if len(normalized_groups[norm_a]) > 1:
                continue  # Ja e duplicata exata
            for j in range(i + 1, len(norms)):
                norm_b = norms[j]
                if len(normalized_groups[norm_b]) > 1:
                    continue
                if (i, j) in checked:
                    continue
                checked.add((i, j))

                sim = self._similarity(norm_a, norm_b)
                if sim >= 0.85:
                    group_a = normalized_groups[norm_a]
                    group_b = normalized_groups[norm_b]
                    all_measures = [(t, m) for t, m, _ in group_a + group_b]
                    dg = DuplicateGroup(
                        canonical_expression=group_a[0][2][:200],
                        measures=all_measures,
                        similarity=round(sim, 2),
                    )
                    report.groups.append(dg)

        report.groups.sort(key=lambda g: g.count, reverse=True)

        logger.info(
            "Analise de duplicatas concluida",
            measures=report.total_measures_analyzed,
            groups=len(report.groups),
            duplicates=report.total_duplicates,
        )
        return report

    def _normalize(self, expression: str) -> str:
        """Normaliza expressao DAX para comparacao."""
        expr = expression.lower()
        # Remove comentarios
        expr = re.sub(r'//.*$', '', expr, flags=re.MULTILINE)
        expr = re.sub(r'/\*.*?\*/', '', expr, flags=re.DOTALL)
        # Remove espacos e newlines
        expr = re.sub(r'\s+', '', expr)
        # Normaliza aspas
        expr = expr.replace("'", "").replace('"', '')
        return expr

    def _similarity(self, a: str, b: str) -> float:
        """Calcula similaridade entre duas strings normalizadas (0-1)."""
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        # Usa coeficiente de Jaccard com trigramas
        def trigrams(s):
            return set(s[i:i+3] for i in range(len(s) - 2))

        ta = trigrams(a)
        tb = trigrams(b)
        if not ta or not tb:
            return 0.0

        intersection = len(ta & tb)
        union = len(ta | tb)
        return intersection / union if union > 0 else 0.0
