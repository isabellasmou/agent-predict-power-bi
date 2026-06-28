"""
Analisador de Impacto de Mudanças.

Responsável por analisar o impacto de uma mudança proposta
no modelo semântico, identificando todos os objetos afetados,
incluindo hierarquias, colunas de ordenação e KPIs.
"""

from dataclasses import dataclass, field
from typing import Optional

import structlog

from pbi_refactor_agent.discovery.dependency_graph import DependencyGraph
from pbi_refactor_agent.models import (
    ChangeType,
    ImpactAnalysis,
    ImpactedObject,
    ObjectType,
    ProposedChange,
    SemanticObject,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# Modelos de impacto estendidos (hierarquias, sortByColumn, KPIs)
# ============================================================================

@dataclass
class HierarchyImpact:
    """Hierarquia impactada por uma mudança."""
    hierarchy_name: str
    table_name: str
    affected_level: str        # nome do nível afetado
    affected_column: str       # coluna referenciada pelo nível
    impact_description: str


@dataclass
class SortByColumnImpact:
    """Coluna cuja ordenação depende da coluna alterada."""
    table_name: str
    column_name: str           # coluna que usa sortByColumn
    sort_by_column: str        # coluna de ordenação (a que está sendo alterada)
    impact_description: str


@dataclass
class KPIImpact:
    """KPI impactado por renomeação de medida."""
    measure_name: str          # medida base do KPI
    table_name: str
    target_expression: Optional[str]
    status_expression: Optional[str]
    trend_expression: Optional[str]
    impact_description: str


@dataclass
class ExtendedImpactAnalysis:
    """
    Extensão do ImpactAnalysis com hierarquias, sortByColumn e KPIs.

    Envolve o ImpactAnalysis original e adiciona os novos campos.
    Use .base para acessar os impactos originais (medidas, relacionamentos).
    """
    base: ImpactAnalysis
    hierarchy_impacts: list = field(default_factory=list)    # list[HierarchyImpact]
    sort_by_impacts: list = field(default_factory=list)      # list[SortByColumnImpact]
    kpi_impacts: list = field(default_factory=list)          # list[KPIImpact]

    @property
    def total_extended_impacts(self) -> int:
        return (
            self.base.total_impacted
            + len(self.hierarchy_impacts)
            + len(self.sort_by_impacts)
            + len(self.kpi_impacts)
        )

    @property
    def has_extended_impacts(self) -> bool:
        return bool(self.hierarchy_impacts or self.sort_by_impacts or self.kpi_impacts)

    def summary_lines(self) -> list[str]:
        lines = [
            f"Total impactados (base): {self.base.total_impacted}",
            f"  - Diretos (DAX): {len(self.base.direct_impacts)}",
            f"  - Cascata: {len(self.base.cascade_impacts)}",
            f"  - Relacionamentos: {len(self.base.relationship_impacts)}",
        ]
        if self.hierarchy_impacts:
            lines.append(f"  - Hierarquias: {len(self.hierarchy_impacts)}")
        if self.sort_by_impacts:
            lines.append(f"  - Ordenações (sortByColumn): {len(self.sort_by_impacts)}")
        if self.kpi_impacts:
            lines.append(f"  - KPIs: {len(self.kpi_impacts)}")
        lines.append(f"Total geral: {self.total_extended_impacts}")
        return lines


# ============================================================================
# ImpactAnalyzer
# ============================================================================

class ImpactAnalyzer:
    """
    Analisador de impacto de mudanças no modelo semântico.

    Analisa impactos em:
    - Expressões DAX (medidas e colunas calculadas)
    - Relacionamentos
    - Hierarquias (NOVO)
    - Colunas com sortByColumn (NOVO)
    - KPIs (NOVO)
    """

    def __init__(self, dependency_graph: DependencyGraph, metadata=None):
        """
        Args:
            dependency_graph: Grafo de dependências do modelo.
            metadata: ModelMetadata opcional — necessário para hierarquias,
                      sortByColumn e KPIs. Se None, apenas o grafo é usado.
        """
        self._graph = dependency_graph
        self._metadata = metadata  # ModelMetadata (opcional)

    # ──────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────

    def analyze(self, change: ProposedChange) -> ImpactAnalysis:
        """
        Análise base (compatível com o código existente).
        Retorna ImpactAnalysis padrão, sem os campos estendidos.
        """
        logger.info(
            "Analisando impacto de mudança",
            change_type=change.change_type.value,
            object_name=change.object_name,
            table_name=change.table_name,
        )

        target_object = self._find_target_object(change)

        if target_object is None:
            logger.warning(
                "Objeto alvo não encontrado",
                object_name=change.object_name,
                table_name=change.table_name,
            )
            target_object = SemanticObject(
                name=change.object_name,
                object_type=self._infer_object_type(change.change_type),
                table_name=change.table_name,
            )

        if change.change_type == ChangeType.RENAME_COLUMN:
            return self._analyze_column_rename(change, target_object)
        elif change.change_type == ChangeType.RENAME_TABLE:
            return self._analyze_table_rename(change, target_object)
        elif change.change_type == ChangeType.RENAME_MEASURE:
            return self._analyze_measure_rename(change, target_object)
        elif change.change_type == ChangeType.DELETE_COLUMN:
            return self._analyze_column_delete(change, target_object)
        elif change.change_type == ChangeType.DELETE_TABLE:
            return self._analyze_table_delete(change, target_object)
        elif change.change_type == ChangeType.MODIFY_EXPRESSION:
            return self._analyze_expression_modify(change, target_object)
        else:
            logger.warning("Tipo de mudança não suportado", change_type=change.change_type.value)
            return ImpactAnalysis(
                change_type=change.change_type,
                target_object=target_object,
                new_value=change.new_value,
            )

    def analyze_extended(self, change: ProposedChange) -> ExtendedImpactAnalysis:
        """
        Análise completa: base + hierarquias + sortByColumn + KPIs.

        Use este método quando quiser o mapeamento completo de impactos.
        """
        base = self.analyze(change)
        extended = ExtendedImpactAnalysis(base=base)

        if self._metadata is None:
            logger.debug("metadata não disponível — pulando análise estendida")
            return extended

        if change.change_type in (ChangeType.RENAME_COLUMN, ChangeType.DELETE_COLUMN):
            table_name = change.table_name or base.target_object.table_name
            column_name = change.object_name
            new_name = change.new_value

            extended.hierarchy_impacts = self._find_hierarchy_impacts_column(
                table_name, column_name, new_name
            )
            extended.sort_by_impacts = self._find_sort_by_impacts(
                table_name, column_name
            )

        elif change.change_type in (ChangeType.RENAME_TABLE, ChangeType.DELETE_TABLE):
            table_name = change.object_name
            extended.hierarchy_impacts = self._find_hierarchy_impacts_table(table_name)

        elif change.change_type == ChangeType.RENAME_MEASURE:
            old_measure = change.object_name
            new_measure = change.new_value
            extended.kpi_impacts = self._find_kpi_impacts(old_measure, new_measure)

        logger.info(
            "Análise estendida concluída",
            hierarchies=len(extended.hierarchy_impacts),
            sort_by=len(extended.sort_by_impacts),
            kpis=len(extended.kpi_impacts),
        )

        return extended

    # ──────────────────────────────────────────────────────────
    # Análises de impacto base (inalteradas)
    # ──────────────────────────────────────────────────────────

    def _analyze_column_rename(self, change, target_object) -> ImpactAnalysis:
        direct_impacts = []
        cascade_impacts = []

        table_name = change.table_name or target_object.table_name
        column_name = change.object_name
        new_name = change.new_value

        referencing_objects = self._graph.find_objects_referencing(table_name, column_name)

        for obj in referencing_objects:
            suggested_expression = self._suggest_rename_in_expression(
                obj.expression, table_name, column_name, new_name
            )
            impact = ImpactedObject(
                object=obj,
                impact_type="direct",
                original_expression=obj.expression,
                suggested_expression=suggested_expression,
                requires_manual_review=self._needs_manual_review(obj, suggested_expression),
            )
            direct_impacts.append(impact)

        for direct_impact in direct_impacts:
            cascade_deps = self._find_cascade_dependencies(direct_impact.object)
            for dep_obj in cascade_deps:
                if dep_obj not in [d.object for d in direct_impacts]:
                    cascade_impact = ImpactedObject(
                        object=dep_obj,
                        impact_type="cascade",
                        original_expression=dep_obj.expression,
                        requires_manual_review=True,
                        notes="Dependência indireta — requer análise",
                    )
                    cascade_impacts.append(cascade_impact)

        relationship_impacts = self._graph.get_relationships_for_column(table_name, column_name)

        logger.info(
            "Análise de impacto concluída",
            direct_impacts=len(direct_impacts),
            cascade_impacts=len(cascade_impacts),
            relationship_impacts=len(relationship_impacts),
        )

        return ImpactAnalysis(
            change_type=change.change_type,
            target_object=target_object,
            new_value=new_name,
            direct_impacts=direct_impacts,
            cascade_impacts=cascade_impacts,
            relationship_impacts=relationship_impacts,
        )

    def _analyze_table_rename(self, change, target_object) -> ImpactAnalysis:
        direct_impacts = []
        old_table_name = change.object_name
        new_table_name = change.new_value

        for obj in self._graph.iterate_objects():
            if obj.expression and old_table_name in obj.expression:
                suggested_expression = self._suggest_table_rename_in_expression(
                    obj.expression, old_table_name, new_table_name
                )
                impact = ImpactedObject(
                    object=obj,
                    impact_type="direct",
                    original_expression=obj.expression,
                    suggested_expression=suggested_expression,
                )
                direct_impacts.append(impact)

        relationship_impacts = [
            rel for rel in self._graph._relationships
            if rel.from_table == old_table_name or rel.to_table == old_table_name
        ]

        return ImpactAnalysis(
            change_type=change.change_type,
            target_object=target_object,
            new_value=new_table_name,
            direct_impacts=direct_impacts,
            relationship_impacts=relationship_impacts,
        )

    def _analyze_measure_rename(self, change, target_object) -> ImpactAnalysis:
        direct_impacts = []
        old_measure_name = change.object_name
        new_measure_name = change.new_value

        for obj in self._graph.iterate_objects():
            if obj.expression and f"[{old_measure_name}]" in obj.expression:
                suggested_expression = obj.expression.replace(
                    f"[{old_measure_name}]", f"[{new_measure_name}]"
                )
                impact = ImpactedObject(
                    object=obj,
                    impact_type="direct",
                    original_expression=obj.expression,
                    suggested_expression=suggested_expression,
                )
                direct_impacts.append(impact)

        return ImpactAnalysis(
            change_type=change.change_type,
            target_object=target_object,
            new_value=new_measure_name,
            direct_impacts=direct_impacts,
        )

    def _analyze_column_delete(self, change, target_object) -> ImpactAnalysis:
        table_name = change.table_name or target_object.table_name
        column_name = change.object_name

        referencing_objects = self._graph.find_objects_referencing(table_name, column_name)
        direct_impacts = [
            ImpactedObject(
                object=obj,
                impact_type="direct",
                original_expression=obj.expression,
                requires_manual_review=True,
                notes="Coluna será excluída — expressão precisa ser reescrita manualmente",
            )
            for obj in referencing_objects
        ]

        relationship_impacts = self._graph.get_relationships_for_column(table_name, column_name)

        return ImpactAnalysis(
            change_type=change.change_type,
            target_object=target_object,
            direct_impacts=direct_impacts,
            relationship_impacts=relationship_impacts,
            requires_manual_review=True,
        )

    def _analyze_table_delete(self, change, target_object) -> ImpactAnalysis:
        table_name = change.object_name
        direct_impacts = [
            ImpactedObject(
                object=obj,
                impact_type="direct",
                original_expression=obj.expression,
                requires_manual_review=True,
                notes="Tabela será excluída — expressão precisa ser reescrita manualmente",
            )
            for obj in self._graph.iterate_objects()
            if obj.expression and table_name in obj.expression
        ]

        relationship_impacts = [
            rel for rel in self._graph._relationships
            if rel.from_table == table_name or rel.to_table == table_name
        ]

        return ImpactAnalysis(
            change_type=change.change_type,
            target_object=target_object,
            direct_impacts=direct_impacts,
            relationship_impacts=relationship_impacts,
            requires_manual_review=True,
        )

    def _analyze_expression_modify(self, change, target_object) -> ImpactAnalysis:
        dependents = self._find_cascade_dependencies(target_object)
        cascade_impacts = [
            ImpactedObject(
                object=dep_obj,
                impact_type="cascade",
                original_expression=dep_obj.expression,
                notes="Dependência indireta — verificar se resultado será afetado",
            )
            for dep_obj in dependents
        ]

        return ImpactAnalysis(
            change_type=change.change_type,
            target_object=target_object,
            new_value=change.new_value,
            cascade_impacts=cascade_impacts,
        )

    # ──────────────────────────────────────────────────────────
    # Análises estendidas (NOVO)
    # ──────────────────────────────────────────────────────────

    def _find_hierarchy_impacts_column(
        self,
        table_name: str,
        column_name: str,
        new_name: Optional[str],
    ) -> list:
        """
        Retorna hierarquias cujos níveis referenciam a coluna alterada.
        """
        impacts = []
        if not self._metadata:
            return impacts

        table_name_lower = table_name.lower()
        column_name_lower = column_name.lower()

        for hierarchy in self._metadata.hierarchies:
            if hierarchy.table_name.lower() != table_name_lower:
                continue

            for level in hierarchy.levels:
                if level.column.lower() == column_name_lower:
                    if new_name:
                        desc = (
                            f"Nível '{level.name}' da hierarquia '{hierarchy.name}' "
                            f"em '{hierarchy.table_name}' referencia '{column_name}'. "
                            f"Deve ser atualizado para '{new_name}'."
                        )
                    else:
                        desc = (
                            f"Nível '{level.name}' da hierarquia '{hierarchy.name}' "
                            f"em '{hierarchy.table_name}' referencia '{column_name}' "
                            f"que será excluída. A hierarquia ficará inválida."
                        )

                    impacts.append(HierarchyImpact(
                        hierarchy_name=hierarchy.name,
                        table_name=hierarchy.table_name,
                        affected_level=level.name,
                        affected_column=column_name,
                        impact_description=desc,
                    ))

        return impacts

    def _find_hierarchy_impacts_table(self, table_name: str) -> list:
        """
        Retorna todas as hierarquias da tabela alterada/excluída.
        """
        impacts = []
        if not self._metadata:
            return impacts

        table_name_lower = table_name.lower()

        for hierarchy in self._metadata.hierarchies:
            if hierarchy.table_name.lower() == table_name_lower:
                desc = (
                    f"Hierarquia '{hierarchy.name}' pertence à tabela '{table_name}' "
                    f"que está sendo alterada. Todos os {len(hierarchy.levels)} "
                    f"nível(is) serão afetados."
                )
                impacts.append(HierarchyImpact(
                    hierarchy_name=hierarchy.name,
                    table_name=hierarchy.table_name,
                    affected_level="(todos)",
                    affected_column="(todos)",
                    impact_description=desc,
                ))

        return impacts

    def _find_sort_by_impacts(self, table_name: str, column_name: str) -> list:
        """
        Retorna colunas que usam a coluna alterada como sortByColumn.
        """
        impacts = []
        if not self._metadata:
            return impacts

        table_name_lower = table_name.lower()
        column_name_lower = column_name.lower()

        for table in self._metadata.business_tables:
            if table.name.lower() != table_name_lower:
                continue

            for col in table.columns:
                if col.sort_by_column and col.sort_by_column.lower() == column_name_lower:
                    desc = (
                        f"A coluna '{col.name}' em '{table.name}' usa '{column_name}' "
                        f"como coluna de ordenação (sortByColumn). "
                        f"Se '{column_name}' for renomeada ou excluída, "
                        f"a ordenação de '{col.name}' quebrará."
                    )
                    impacts.append(SortByColumnImpact(
                        table_name=table.name,
                        column_name=col.name,
                        sort_by_column=column_name,
                        impact_description=desc,
                    ))

        return impacts

    def _find_kpi_impacts(
        self,
        old_measure_name: str,
        new_measure_name: Optional[str],
    ) -> list:
        """
        Retorna KPIs impactados por renomeação de medida.

        Um KPI é impactado quando:
        - A medida base do KPI é a medida renomeada
        - A target_expression ou status_expression referencia a medida renomeada
        """
        impacts = []
        if not self._metadata:
            return impacts

        old_ref = f"[{old_measure_name}]"
        old_ref_lower = old_ref.lower()

        for table in self._metadata.business_tables:
            for measure in table.measures:
                if not measure.kpi:
                    continue

                kpi = measure.kpi
                affected = False
                reasons = []

                # Medida base é a renomeada
                if measure.name.lower() == old_measure_name.lower():
                    affected = True
                    reasons.append("esta é a medida base do KPI")

                # target_expression referencia a medida
                if kpi.target_expression and old_ref_lower in kpi.target_expression.lower():
                    affected = True
                    reasons.append("target_expression referencia a medida")

                # status_expression referencia a medida
                if kpi.status_expression and old_ref_lower in kpi.status_expression.lower():
                    affected = True
                    reasons.append("status_expression referencia a medida")

                # trend_expression referencia a medida
                if kpi.trend_expression and old_ref_lower in kpi.trend_expression.lower():
                    affected = True
                    reasons.append("trend_expression referencia a medida")

                if affected:
                    if new_measure_name:
                        desc = (
                            f"KPI da medida '{measure.name}' em '{table.name}' "
                            f"será impactado pela renomeação de '{old_measure_name}' "
                            f"para '{new_measure_name}'. "
                            f"Motivo(s): {', '.join(reasons)}."
                        )
                    else:
                        desc = (
                            f"KPI da medida '{measure.name}' em '{table.name}' "
                            f"depende de '{old_measure_name}'. "
                            f"Motivo(s): {', '.join(reasons)}."
                        )

                    impacts.append(KPIImpact(
                        measure_name=measure.name,
                        table_name=table.name,
                        target_expression=kpi.target_expression,
                        status_expression=kpi.status_expression,
                        trend_expression=kpi.trend_expression,
                        impact_description=desc,
                    ))

        return impacts

    # ──────────────────────────────────────────────────────────
    # Helpers internos (inalterados + melhorias de regex)
    # ──────────────────────────────────────────────────────────

    def _find_target_object(self, change: ProposedChange) -> Optional[SemanticObject]:
        object_type = self._infer_object_type(change.change_type)
        return self._graph.find_by_name(
            name=change.object_name,
            table_name=change.table_name,
            object_type=object_type,
        )

    def _infer_object_type(self, change_type: ChangeType) -> ObjectType:
        mapping = {
            ChangeType.RENAME_COLUMN: ObjectType.COLUMN,
            ChangeType.DELETE_COLUMN: ObjectType.COLUMN,
            ChangeType.RENAME_TABLE: ObjectType.TABLE,
            ChangeType.DELETE_TABLE: ObjectType.TABLE,
            ChangeType.RENAME_MEASURE: ObjectType.MEASURE,
            ChangeType.MODIFY_EXPRESSION: ObjectType.MEASURE,
        }
        return mapping.get(change_type, ObjectType.COLUMN)

    def _suggest_rename_in_expression(
        self,
        expression: str,
        table_name: str,
        old_name: str,
        new_name: str,
    ) -> str:
        if not expression or not new_name:
            return expression or ""

        import re as _re

        # Substitui com e sem aspas simples, case-insensitive
        patterns = [
            (
                _re.compile(
                    rf"'{_re.escape(table_name)}'\[{_re.escape(old_name)}\]",
                    _re.IGNORECASE,
                ),
                f"'{table_name}'[{new_name}]",
            ),
            (
                _re.compile(
                    rf"\b{_re.escape(table_name)}\[{_re.escape(old_name)}\]",
                    _re.IGNORECASE,
                ),
                f"{table_name}[{new_name}]",
            ),
        ]

        result = expression
        for pattern, replacement in patterns:
            result = pattern.sub(replacement, result)

        return result

    def _suggest_table_rename_in_expression(
        self,
        expression: str,
        old_table_name: str,
        new_table_name: str,
    ) -> str:
        import re as _re

        patterns = [
            (
                _re.compile(rf"'{_re.escape(old_table_name)}'", _re.IGNORECASE),
                f"'{new_table_name}'",
            ),
            (
                _re.compile(rf"\b{_re.escape(old_table_name)}\[", _re.IGNORECASE),
                f"{new_table_name}[",
            ),
        ]

        result = expression
        for pattern, replacement in patterns:
            result = pattern.sub(replacement, result)

        return result

    def _find_cascade_dependencies(self, obj: SemanticObject) -> list:
        node_id = self._get_node_id(obj)
        dependencies = self._graph.get_all_dependents(node_id)
        return [dep.target for dep in dependencies if dep.depth > 1]

    def _get_node_id(self, obj: SemanticObject) -> str:
        prefix = obj.object_type.value
        if obj.table_name:
            return f"{prefix}:{obj.table_name}.{obj.name}"
        return f"{prefix}:{obj.name}"

    def _needs_manual_review(self, obj: SemanticObject, suggested_expression: str) -> bool:
        if obj.expression:
            if len(obj.expression) > 500:
                return True
            if obj.expression.upper().count("CALCULATE") > 2:
                return True
        return False