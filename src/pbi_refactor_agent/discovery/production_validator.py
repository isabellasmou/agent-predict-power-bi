"""
Validador Preditivo de Producao.

Analisa o modelo ANTES de publicar/atualizar e detecta problemas
que VAO acontecer (integridade referencial, performance, referencias
quebradas, etc.). O foco e PREVENIR problemas, nao reagir a eles.

Filosofia: "Pre-flight check" completo antes de ir para producao.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class RiskLevel(str, Enum):
    """Nivel de risco de uma validacao."""
    SAFE = "safe"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ValidationCategory(str, Enum):
    """Categoria de validacao."""
    INTEGRITY = "Integridade Referencial"
    REFERENCES = "Referencias"
    PERFORMANCE = "Performance"
    SCHEMA = "Schema Evolution"
    CARDINALITY = "Cardinalidade"
    DATA_TYPES = "Tipos de Dados"


@dataclass
class ValidationIssue:
    """Um problema detectado na validacao preditiva."""
    category: ValidationCategory
    risk_level: RiskLevel
    title: str
    description: str
    impact: str  # O que vai acontecer se nao corrigir
    recommendation: str  # Como corrigir
    affected_objects: list[str] = field(default_factory=list)
    sql_query: Optional[str] = None  # Query SQL para verificar na fonte


@dataclass
class ProductionValidationReport:
    """Relatorio completo de validacao preditiva."""
    issues: list[ValidationIssue] = field(default_factory=list)
    
    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.risk_level == RiskLevel.CRITICAL)
    
    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.risk_level == RiskLevel.WARNING)
    
    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.risk_level == RiskLevel.INFO)
    
    @property
    def is_safe_for_production(self) -> bool:
        """True se nao ha nenhum problema critico."""
        return self.critical_count == 0
    
    @property
    def risk_score(self) -> float:
        """Score de risco de 0 (safe) a 100 (muito arriscado)."""
        penalty = self.critical_count * 25 + self.warning_count * 10 + self.info_count * 2
        return min(100, penalty)
    
    @property
    def grade(self) -> str:
        """Nota de seguranca (A-F)."""
        score = 100 - self.risk_score
        if score >= 95:
            return "A+"
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"


class ProductionValidator:
    """
    Validador preditivo de producao.
    
    Executa verificacoes ANTES de publicar/atualizar para detectar
    problemas que VAO acontecer (nao que JA aconteceram).
    """
    
    def validate(self, metadata, graph) -> ProductionValidationReport:
        """
        Executa validacao preditiva completa.
        
        Args:
            metadata: ModelMetadata extraido do .pbit.
            graph: DependencyGraph populado.
        
        Returns:
            ProductionValidationReport com todos os riscos detectados.
        """
        report = ProductionValidationReport()
        
        # Executar todas as verificacoes preditivas
        self._check_null_foreign_keys(metadata, report)
        self._check_broken_references(metadata, graph, report)
        self._check_performance_risks(metadata, report)
        self._check_many_to_many(metadata, report)
        self._check_inactive_relationships_usage(metadata, graph, report)
        self._check_missing_relationships(metadata, report)
        self._check_high_cardinality_strings(metadata, report)
        self._check_circular_dependencies(graph, report)
        self._check_bidirectional_filters(metadata, report)
        
        logger.info(
            "Validacao preditiva concluida",
            critical=report.critical_count,
            warning=report.warning_count,
            safe=report.is_safe_for_production,
        )
        return report
    
    def _check_null_foreign_keys(self, metadata, report: ProductionValidationReport):
        """Detecta colunas FK que podem ter NULL (causa NullKeyNotAllowed)."""
        for rel in metadata.relationships:
            # FK esta no lado "from" do relacionamento
            from_table = next((t for t in metadata.business_tables if t.name == rel.from_table), None)
            if not from_table:
                continue
            
            from_col = next((c for c in from_table.columns if c.name == rel.from_column), None)
            if not from_col:
                continue
            
            # Se a coluna nao e marcada como chave e nao tem restricao, pode ter NULL
            if not getattr(from_col, "is_key", False):
                report.issues.append(ValidationIssue(
                    category=ValidationCategory.INTEGRITY,
                    risk_level=RiskLevel.CRITICAL,
                    title=f"FK pode ter NULL: {rel.from_table}.{rel.from_column}",
                    description=(
                        f"Coluna {rel.from_column} da tabela {rel.from_table} e usada como "
                        f"chave estrangeira mas nao tem restricao NOT NULL."
                    ),
                    impact="Refresh vai FALHAR com erro 'NullKeyNotAllowed' se houver valores NULL.",
                    recommendation=(
                        f"1. Adicione filtro na query da fonte: WHERE {rel.from_column} IS NOT NULL\n"
                        f"2. Ou adicione DEFAULT na coluna\n"
                        f"3. Ou use coluna calculada com tratamento: IF(ISBLANK(...), -1, ...)"
                    ),
                    affected_objects=[rel.full_name],
                    sql_query=f"SELECT COUNT(*) as null_count FROM {rel.from_table} WHERE {rel.from_column} IS NULL",
                ))
    
    def _check_broken_references(self, metadata, graph, report: ProductionValidationReport):
        """Detecta medidas que referenciam objetos que nao existem."""
        # Coleta todos os nomes de colunas e tabelas existentes
        existing_columns = set()
        existing_tables = set()
        
        for table in metadata.business_tables:
            existing_tables.add(table.name.upper())
            for col in table.columns:
                existing_columns.add(f"{table.name.upper()}[{col.name.upper()}]")
        
        # Verifica cada medida
        for table in metadata.business_tables:
            for measure in table.measures:
                if not measure.expression:
                    continue
                
                expr_upper = measure.expression.upper()
                
                # Regex simplificado para detectar referencias
                import re
                # Encontra 'Tabela'[Coluna] ou Tabela[Coluna]
                refs = re.findall(r"'?([A-Z_][A-Z0-9_]*)'?\[([A-Z_][A-Z0-9_]*)\]", expr_upper, re.IGNORECASE)
                
                for tbl, col in refs:
                    ref = f"{tbl.upper()}[{col.upper()}]"
                    if ref not in existing_columns:
                        # Verifica se pelo menos a tabela existe
                        if tbl.upper() not in existing_tables:
                            report.issues.append(ValidationIssue(
                                category=ValidationCategory.REFERENCES,
                                risk_level=RiskLevel.CRITICAL,
                                title=f"Referencia quebrada em {table.name}[{measure.name}]",
                                description=f"Medida referencia '{tbl}[{col}]' que nao existe no modelo.",
                                impact="Medida vai retornar erro ao ser calculada no refresh/query.",
                                recommendation=f"Verifique se a tabela '{tbl}' foi renomeada ou removida.",
                                affected_objects=[f"{table.name}[{measure.name}]"],
                            ))
    
    def _check_performance_risks(self, metadata, report: ProductionValidationReport):
        """Detecta padroes DAX que vao causar problemas de performance."""
        for table in metadata.business_tables:
            for measure in table.measures:
                if not measure.expression:
                    continue
                
                expr_upper = measure.expression.upper()
                
                # Detecta FILTER(ALL(...)) sobre tabelas grandes
                if "FILTER" in expr_upper and "ALL(" in expr_upper:
                    # Heuristica: se a tabela tem muitas colunas, e provavelmente grande
                    if len(table.columns) > 15:
                        report.issues.append(ValidationIssue(
                            category=ValidationCategory.PERFORMANCE,
                            risk_level=RiskLevel.WARNING,
                            title=f"Performance: FILTER(ALL(...)) em {table.name}[{measure.name}]",
                            description=(
                                f"Medida usa FILTER sobre tabela inteira ({table.name}, "
                                f"{len(table.columns)} colunas)."
                            ),
                            impact="Pode causar timeout em queries e refresh lento.",
                            recommendation="Use CALCULATE com filtros de contexto em vez de FILTER(ALL(...)).",
                            affected_objects=[f"{table.name}[{measure.name}]"],
                        ))
                
                # Detecta iteradores sem filtro
                iterators = ["SUMX", "AVERAGEX", "COUNTX", "MAXX", "MINX"]
                for it in iterators:
                    if f"{it}(" in expr_upper:
                        # Se nao tem FILTER ou TOPN, esta iterando a tabela inteira
                        if "FILTER" not in expr_upper and "TOPN" not in expr_upper:
                            report.issues.append(ValidationIssue(
                                category=ValidationCategory.PERFORMANCE,
                                risk_level=RiskLevel.WARNING,
                                title=f"Performance: {it} sem filtro em {table.name}[{measure.name}]",
                                description=f"Medida usa {it} sobre tabela inteira sem filtro.",
                                impact="Em tabelas grandes (>100k linhas), pode ser muito lento.",
                                recommendation=f"Use {it}(FILTER(...), ...) para iterar apenas linhas relevantes.",
                                affected_objects=[f"{table.name}[{measure.name}]"],
                            ))
    
    def _check_many_to_many(self, metadata, report: ProductionValidationReport):
        """Detecta relacionamentos many-to-many que podem causar resultados incorretos."""
        for rel in metadata.relationships:
            if "many" in rel.cardinality.lower() and rel.cardinality.count("many") == 2:
                report.issues.append(ValidationIssue(
                    category=ValidationCategory.CARDINALITY,
                    risk_level=RiskLevel.WARNING,
                    title=f"Many-to-many: {rel.from_table} <-> {rel.to_table}",
                    description=f"Relacionamento {rel.full_name} e many:many.",
                    impact="Pode causar resultados duplicados ou incorretos em medidas.",
                    recommendation=(
                        "1. Use tabela bridge entre as duas tabelas\n"
                        "2. Ou revise o modelo dimensional (pode estar desnormalizado)"
                    ),
                    affected_objects=[rel.full_name],
                ))
    
    def _check_inactive_relationships_usage(self, metadata, graph, report: ProductionValidationReport):
        """Verifica se relacionamentos inativos sao usados via USERELATIONSHIP."""
        inactive = [r for r in metadata.relationships if not r.is_active]
        if not inactive:
            return
        
        # Verifica se alguma medida usa USERELATIONSHIP
        for rel in inactive:
            used = False
            for table in metadata.business_tables:
                for measure in table.measures:
                    if measure.expression and "USERELATIONSHIP" in measure.expression.upper():
                        used = True
                        break
                if used:
                    break
            
            if not used:
                report.issues.append(ValidationIssue(
                    category=ValidationCategory.INTEGRITY,
                    risk_level=RiskLevel.INFO,
                    title=f"Relacionamento inativo nao utilizado: {rel.from_table} -> {rel.to_table}",
                    description=f"Relacionamento {rel.full_name} esta inativo e nao e usado via USERELATIONSHIP().",
                    impact="Relacionamento nao tem efeito no modelo. Ocupa memoria inutilmente.",
                    recommendation="Remova o relacionamento ou ative-o se for necessario.",
                    affected_objects=[rel.full_name],
                ))
    
    def _check_missing_relationships(self, metadata, report: ProductionValidationReport):
        """Detecta tabelas que deveriam ter relacionamento mas nao tem (by naming convention)."""
        # Heuristica: se uma tabela tem coluna terminando em "Key" ou "ID" com mesmo nome de outra tabela
        for table in metadata.business_tables:
            for col in table.columns:
                col_name_upper = col.name.upper()
                
                # Procura por colunas que parecem FKs
                if col_name_upper.endswith("KEY") or col_name_upper.endswith("ID"):
                    # Remove sufixo
                    base_name = col_name_upper.replace("KEY", "").replace("ID", "").strip("_")
                    
                    # Procura tabela com nome similar
                    for other_table in metadata.business_tables:
                        if other_table.name == table.name:
                            continue
                        
                        if base_name in other_table.name.upper() or other_table.name.upper() in base_name:
                            # Verifica se JA existe relacionamento
                            has_rel = any(
                                (r.from_table == table.name and r.to_table == other_table.name) or
                                (r.from_table == other_table.name and r.to_table == table.name)
                                for r in metadata.relationships
                            )
                            
                            if not has_rel:
                                report.issues.append(ValidationIssue(
                                    category=ValidationCategory.INTEGRITY,
                                    risk_level=RiskLevel.INFO,
                                    title=f"Relacionamento faltando? {table.name} -> {other_table.name}",
                                    description=(
                                        f"Tabela {table.name} tem coluna {col.name} que parece FK "
                                        f"para {other_table.name}, mas nao ha relacionamento."
                                    ),
                                    impact="Se o relacionamento e necessario, filtros nao vao funcionar.",
                                    recommendation=f"Crie relacionamento {table.name}[{col.name}] -> {other_table.name}[?]",
                                    affected_objects=[f"{table.name}[{col.name}]"],
                                ))
                                break  # Evita duplicatas
    
    def _check_high_cardinality_strings(self, metadata, report: ProductionValidationReport):
        """Detecta colunas string que podem ter alta cardinalidade (impacto em memoria)."""
        for table in metadata.business_tables:
            for col in table.columns:
                # Se e string e o nome sugere alta cardinalidade
                if col.data_type == "string":
                    col_lower = col.name.lower()
                    high_card_names = ["id", "key", "code", "codigo", "guid", "hash", "uuid"]
                    
                    if any(h in col_lower for h in high_card_names):
                        # Verifica se esta sendo usada em relacionamento
                        is_in_rel = any(
                            (r.from_column == col.name and r.from_table == table.name) or
                            (r.to_column == col.name and r.to_table == table.name)
                            for r in metadata.relationships
                        )
                        
                        if is_in_rel:
                            report.issues.append(ValidationIssue(
                                category=ValidationCategory.DATA_TYPES,
                                risk_level=RiskLevel.WARNING,
                                title=f"Coluna string em relacionamento: {table.name}.{col.name}",
                                description=(
                                    f"Coluna {col.name} e do tipo string e usada em relacionamento. "
                                    f"Strings tem alta cardinalidade e consomem muita memoria."
                                ),
                                impact="Modelo pode ficar lento e consumir muita memoria.",
                                recommendation="Se possivel, use tipo numerico (int64) para chaves.",
                                affected_objects=[f"{table.name}[{col.name}]"],
                            ))
    
    def _check_circular_dependencies(self, graph, report: ProductionValidationReport):
        """Detecta dependencias circulares que vao causar erro de calculo."""
        # Usa o grafo para detectar ciclos
        import networkx as nx
        
        try:
            # Tenta achar ciclos no grafo
            cycles = list(nx.simple_cycles(graph._graph))
            
            for cycle in cycles:
                # Converte IDs de nos em nomes
                cycle_names = []
                for node_id in cycle:
                    obj = graph.get_object(node_id)
                    if obj:
                        cycle_names.append(obj.full_name)
                
                if cycle_names:
                    report.issues.append(ValidationIssue(
                        category=ValidationCategory.REFERENCES,
                        risk_level=RiskLevel.CRITICAL,
                        title=f"Dependencia circular detectada",
                        description=f"Ciclo de dependencias: {' -> '.join(cycle_names)} -> {cycle_names[0]}",
                        impact="Power BI vai retornar erro 'Circular dependency' no refresh.",
                        recommendation="Refatore as medidas para quebrar o ciclo de dependencias.",
                        affected_objects=cycle_names,
                    ))
        except Exception:
            # Se der erro ao procurar ciclos, ignora
            pass
    
    def _check_bidirectional_filters(self, metadata, report: ProductionValidationReport):
        """Detecta filtros bidirecionais que podem causar ambiguidade."""
        bidir = [
            r for r in metadata.relationships
            if r.cross_filtering.lower() in ("bothdirections", "both", "bidirectional")
        ]
        
        if len(bidir) > 2:
            report.issues.append(ValidationIssue(
                category=ValidationCategory.CARDINALITY,
                risk_level=RiskLevel.WARNING,
                title=f"Multiplos filtros bidirecionais ({len(bidir)})",
                description=(
                    f"Modelo tem {len(bidir)} relacionamentos bidirecionais. "
                    f"Isso pode causar ambiguidade em filtros."
                ),
                impact="Resultados podem ser incorretos ou inesperados.",
                recommendation="Use filtros bidirecionais apenas quando absolutamente necessario.",
                affected_objects=[r.full_name for r in bidir],
            ))
