"""
Modelos de dados do PBI Refactor Agent.

Define as estruturas de dados para representar objetos do modelo semântico,
análises de impacto e resultados de refatoração.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    """Tipos de mudança suportados."""
    RENAME_COLUMN = "rename_column"
    RENAME_TABLE = "rename_table"
    RENAME_MEASURE = "rename_measure"
    DELETE_COLUMN = "delete_column"
    DELETE_TABLE = "delete_table"
    MODIFY_EXPRESSION = "modify_expression"
    MODIFY_RELATIONSHIP = "modify_relationship"


class ObjectType(str, Enum):
    """Tipos de objetos do modelo semântico."""
    TABLE = "table"
    COLUMN = "column"
    MEASURE = "measure"
    CALCULATED_COLUMN = "calculated_column"
    RELATIONSHIP = "relationship"
    CALCULATION_GROUP = "calculation_group"
    CALCULATION_ITEM = "calculation_item"
    HIERARCHY = "hierarchy"
    PARTITION = "partition"


class ValidationStatus(str, Enum):
    """Status de validação."""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class RefactorStatus(str, Enum):
    """Status de refatoração."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# ============================================================
# Modelos de Objetos do Modelo Semântico
# ============================================================

class SemanticObject(BaseModel):
    """Objeto base do modelo semântico."""
    name: str = Field(..., description="Nome do objeto")
    object_type: ObjectType = Field(..., description="Tipo do objeto")
    table_name: Optional[str] = Field(None, description="Nome da tabela pai (se aplicável)")
    expression: Optional[str] = Field(None, description="Expressão DAX (se aplicável)")
    description: Optional[str] = Field(None, description="Descrição do objeto")
    
    @property
    def full_name(self) -> str:
        """Nome completo do objeto (Tabela[Coluna] ou [Medida])."""
        if self.table_name:
            return f"'{self.table_name}'[{self.name}]"
        return f"[{self.name}]"
    
    class Config:
        use_enum_values = True


class TableInfo(SemanticObject):
    """Informações de uma tabela."""
    object_type: ObjectType = ObjectType.TABLE
    columns: list[str] = Field(default_factory=list, description="Lista de colunas")
    measures: list[str] = Field(default_factory=list, description="Lista de medidas")
    calculated_columns: list[str] = Field(default_factory=list, description="Colunas calculadas")
    row_count: Optional[int] = Field(None, description="Número de linhas")


class ColumnInfo(SemanticObject):
    """Informações de uma coluna."""
    object_type: ObjectType = ObjectType.COLUMN
    data_type: str = Field(..., description="Tipo de dados")
    is_nullable: bool = Field(True, description="Se permite nulos")
    is_key: bool = Field(False, description="Se é chave primária")


class MeasureInfo(SemanticObject):
    """Informações de uma medida."""
    object_type: ObjectType = ObjectType.MEASURE
    format_string: Optional[str] = Field(None, description="String de formato")
    display_folder: Optional[str] = Field(None, description="Pasta de exibição")


class CalculatedColumnInfo(SemanticObject):
    """Informações de uma coluna calculada."""
    object_type: ObjectType = ObjectType.CALCULATED_COLUMN
    data_type: str = Field(..., description="Tipo de dados")


class RelationshipInfo(BaseModel):
    """Informações de um relacionamento."""
    name: str = Field(..., description="Nome do relacionamento")
    from_table: str = Field(..., description="Tabela de origem")
    from_column: str = Field(..., description="Coluna de origem")
    to_table: str = Field(..., description="Tabela de destino")
    to_column: str = Field(..., description="Coluna de destino")
    is_active: bool = Field(True, description="Se o relacionamento está ativo")
    cross_filter_direction: str = Field("Single", description="Direção do filtro cruzado")
    
    @property
    def full_name(self) -> str:
        """Nome completo do relacionamento."""
        return f"{self.from_table}[{self.from_column}] -> {self.to_table}[{self.to_column}]"


# ============================================================
# Modelos de Dependência e Impacto
# ============================================================

class Dependency(BaseModel):
    """Representa uma dependência entre objetos."""
    source: SemanticObject = Field(..., description="Objeto de origem")
    target: SemanticObject = Field(..., description="Objeto dependente")
    dependency_type: str = Field("direct", description="Tipo de dependência (direct/indirect)")
    depth: int = Field(1, description="Profundidade na árvore de dependências")


class ImpactedObject(BaseModel):
    """Objeto impactado por uma mudança."""
    object: SemanticObject = Field(..., description="Objeto impactado")
    impact_type: str = Field(..., description="Tipo de impacto (direct/cascade)")
    original_expression: Optional[str] = Field(None, description="Expressão original")
    suggested_expression: Optional[str] = Field(None, description="Expressão sugerida")
    requires_manual_review: bool = Field(False, description="Requer revisão manual")
    notes: Optional[str] = Field(None, description="Notas adicionais")


class ImpactAnalysis(BaseModel):
    """Resultado da análise de impacto de uma mudança."""
    change_type: ChangeType = Field(..., description="Tipo de mudança")
    target_object: SemanticObject = Field(..., description="Objeto alvo da mudança")
    new_value: Optional[str] = Field(None, description="Novo valor (ex: novo nome)")
    
    # Objetos impactados
    direct_impacts: list[ImpactedObject] = Field(
        default_factory=list,
        description="Impactos diretos"
    )
    cascade_impacts: list[ImpactedObject] = Field(
        default_factory=list,
        description="Impactos em cascata"
    )
    relationship_impacts: list[RelationshipInfo] = Field(
        default_factory=list,
        description="Relacionamentos impactados"
    )
    
    # Metadados
    timestamp: datetime = Field(default_factory=datetime.now, description="Data da análise")
    total_impacted: int = Field(0, description="Total de objetos impactados")
    requires_manual_review: bool = Field(False, description="Algum objeto requer revisão manual")
    
    def model_post_init(self, __context: Any) -> None:
        """Calcula campos derivados após inicialização."""
        self.total_impacted = (
            len(self.direct_impacts) 
            + len(self.cascade_impacts) 
            + len(self.relationship_impacts)
        )
        self.requires_manual_review = any(
            impact.requires_manual_review 
            for impact in self.direct_impacts + self.cascade_impacts
        )


# ============================================================
# Modelos de Validação
# ============================================================

class SyntaxValidation(BaseModel):
    """Resultado de validação sintática."""
    is_valid: bool = Field(..., description="Se a sintaxe é válida")
    error_message: Optional[str] = Field(None, description="Mensagem de erro")
    error_line: Optional[int] = Field(None, description="Linha do erro")
    error_column: Optional[int] = Field(None, description="Coluna do erro")


class EquivalenceValidation(BaseModel):
    """Resultado de validação de equivalência numérica."""
    is_equivalent: bool = Field(..., description="Se os resultados são equivalentes")
    original_result: Any = Field(None, description="Resultado original")
    refactored_result: Any = Field(None, description="Resultado refatorado")
    difference: Optional[float] = Field(None, description="Diferença numérica")
    tolerance_used: float = Field(0.0001, description="Tolerância utilizada")
    sample_query: Optional[str] = Field(None, description="Query DAX usada no teste")


class PerformanceValidation(BaseModel):
    """Resultado de validação de performance."""
    original_time_ms: float = Field(..., description="Tempo original em ms")
    refactored_time_ms: float = Field(..., description="Tempo refatorado em ms")
    time_difference_ms: float = Field(..., description="Diferença em ms")
    percentage_change: float = Field(..., description="Variação percentual")
    is_acceptable: bool = Field(..., description="Se a performance é aceitável")
    threshold_ms: float = Field(5000, description="Threshold utilizado")


class ValidationResult(BaseModel):
    """Resultado completo de validação de uma expressão refatorada."""
    object: SemanticObject = Field(..., description="Objeto validado")
    status: ValidationStatus = Field(..., description="Status da validação")
    
    syntax: Optional[SyntaxValidation] = Field(None, description="Validação sintática")
    equivalence: Optional[EquivalenceValidation] = Field(None, description="Validação de equivalência")
    performance: Optional[PerformanceValidation] = Field(None, description="Validação de performance")
    
    error_message: Optional[str] = Field(None, description="Mensagem de erro geral")
    timestamp: datetime = Field(default_factory=datetime.now, description="Data da validação")
    
    @property
    def is_valid(self) -> bool:
        """Retorna se todas as validações passaram."""
        return self.status == ValidationStatus.PASSED


# ============================================================
# Modelos de Refatoração
# ============================================================

class RefactorItem(BaseModel):
    """Item individual de refatoração."""
    object: SemanticObject = Field(..., description="Objeto refatorado")
    original_expression: str = Field(..., description="Expressão original")
    refactored_expression: str = Field(..., description="Expressão refatorada")
    
    llm_provider: str = Field(..., description="Provedor de LLM usado")
    llm_model: str = Field(..., description="Modelo de LLM usado")
    confidence_score: float = Field(0.0, description="Score de confiança (0-1)")
    
    validation: Optional[ValidationResult] = Field(None, description="Resultado da validação")
    applied: bool = Field(False, description="Se foi aplicado ao modelo")
    
    @property
    def is_validated(self) -> bool:
        """Retorna se o item foi validado com sucesso."""
        return self.validation is not None and self.validation.is_valid


class RefactorResult(BaseModel):
    """Resultado completo de uma operação de refatoração."""
    impact_analysis: ImpactAnalysis = Field(..., description="Análise de impacto original")
    status: RefactorStatus = Field(..., description="Status da refatoração")
    
    items: list[RefactorItem] = Field(
        default_factory=list,
        description="Itens refatorados"
    )
    
    # Estatísticas
    total_items: int = Field(0, description="Total de itens")
    successful_items: int = Field(0, description="Itens bem-sucedidos")
    failed_items: int = Field(0, description="Itens com falha")
    skipped_items: int = Field(0, description="Itens ignorados")
    
    # Transação
    transaction_id: Optional[str] = Field(None, description="ID da transação")
    applied: bool = Field(False, description="Se foi aplicado ao modelo")
    rolled_back: bool = Field(False, description="Se foi revertido")
    
    # Metadados
    start_time: datetime = Field(default_factory=datetime.now, description="Início")
    end_time: Optional[datetime] = Field(None, description="Fim")
    duration_seconds: Optional[float] = Field(None, description="Duração em segundos")
    
    error_message: Optional[str] = Field(None, description="Mensagem de erro geral")
    
    def model_post_init(self, __context: Any) -> None:
        """Calcula campos derivados após inicialização."""
        self.total_items = len(self.items)
        self.successful_items = sum(1 for item in self.items if item.is_validated)
        self.failed_items = sum(
            1 for item in self.items 
            if item.validation and not item.validation.is_valid
        )
        self.skipped_items = sum(
            1 for item in self.items 
            if item.validation is None
        )
    
    def summary(self) -> str:
        """Retorna um resumo textual do resultado."""
        lines = [
            f"Refatoração: {self.status.value}",
            f"Total de itens: {self.total_items}",
            f"  - Sucesso: {self.successful_items}",
            f"  - Falha: {self.failed_items}",
            f"  - Ignorados: {self.skipped_items}",
            f"Aplicado: {'Sim' if self.applied else 'Não'}",
        ]
        
        if self.rolled_back:
            lines.append("Revertido: Sim")
        
        if self.duration_seconds:
            lines.append(f"Duração: {self.duration_seconds:.2f}s")
        
        if self.error_message:
            lines.append(f"Erro: {self.error_message}")
        
        return "\n".join(lines)


# ============================================================
# Modelos de Mudança Proposta
# ============================================================

class ProposedChange(BaseModel):
    """Mudança proposta pelo usuário."""
    change_type: ChangeType = Field(..., description="Tipo de mudança")
    table_name: Optional[str] = Field(None, description="Nome da tabela")
    object_name: str = Field(..., description="Nome do objeto")
    new_value: Optional[str] = Field(None, description="Novo valor")
    
    # Opções
    validate_before_apply: bool = Field(True, description="Validar antes de aplicar")
    dry_run: bool = Field(False, description="Apenas simular, não aplicar")
    auto_rollback_on_failure: bool = Field(True, description="Reverter em caso de falha")
    
    def to_dict(self) -> dict:
        """Converte para dicionário."""
        return self.model_dump()
