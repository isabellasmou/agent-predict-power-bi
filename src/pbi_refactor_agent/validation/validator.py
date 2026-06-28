"""
Validador DAX Completo.

Orquestra todas as validações (sintaxe, equivalência, performance)
para expressões DAX refatoradas.
"""

from typing import Optional

import structlog

from pbi_refactor_agent.config import Settings, get_settings
from pbi_refactor_agent.models import (
    RefactorItem,
    RefactorResult,
    SemanticObject,
    ValidationResult,
    ValidationStatus,
)
from pbi_refactor_agent.validation.equivalence_tester import EquivalenceTester
from pbi_refactor_agent.validation.performance_analyzer import PerformanceAnalyzer
from pbi_refactor_agent.validation.syntax_validator import SyntaxValidator

logger = structlog.get_logger(__name__)


class DAXValidator:
    """
    Validador completo de expressões DAX refatoradas.
    
    Combina validação sintática, teste de equivalência numérica
    e análise de performance em um único fluxo.
    """
    
    def __init__(
        self,
        mcp_client=None,
        settings: Optional[Settings] = None
    ):
        """
        Inicializa o validador.
        
        Args:
            mcp_client: Cliente MCP para validações que requerem execução.
            settings: Configurações do agente.
        """
        self._settings = settings or get_settings()
        self._mcp_client = mcp_client
        
        # Inicializa sub-validadores
        self._syntax_validator = SyntaxValidator(mcp_client=mcp_client)
        self._equivalence_tester = EquivalenceTester(
            mcp_client=mcp_client,
            tolerance=self._settings.numeric_tolerance,
            timeout_seconds=self._settings.validation_timeout
        )
        self._performance_analyzer = PerformanceAnalyzer(
            mcp_client=mcp_client,
            threshold_ms=self._settings.max_execution_time_ms
        )
        
        logger.info("DAXValidator inicializado")
    
    async def validate(
        self,
        refactor_item: RefactorItem,
        skip_equivalence: bool = False,
        skip_performance: bool = False
    ) -> ValidationResult:
        """
        Valida um item de refatoração.
        
        Args:
            refactor_item: Item de refatoração a validar.
            skip_equivalence: Se True, pula teste de equivalência.
            skip_performance: Se True, pula análise de performance.
            
        Returns:
            Resultado da validação completa.
        """
        obj = refactor_item.object
        
        logger.info(
            "Validando item refatorado",
            object_name=obj.name,
            skip_equivalence=skip_equivalence,
            skip_performance=skip_performance
        )
        
        # 1. Validação sintática
        syntax_result = self._syntax_validator.validate(
            refactor_item.refactored_expression
        )
        
        if not syntax_result.is_valid:
            logger.warning(
                "Falha na validação sintática",
                object_name=obj.name,
                error=syntax_result.error_message
            )
            return ValidationResult(
                object=obj,
                status=ValidationStatus.FAILED,
                syntax=syntax_result,
                error_message=f"Erro de sintaxe: {syntax_result.error_message}"
            )
        
        # 2. Teste de equivalência (se não skipado)
        equivalence_result = None
        if not skip_equivalence and self._mcp_client:
            equivalence_result = await self._equivalence_tester.test_equivalence(
                original_expression=refactor_item.original_expression,
                refactored_expression=refactor_item.refactored_expression,
                object_name=obj.name,
                table_name=obj.table_name
            )
            
            if not equivalence_result.is_equivalent:
                logger.warning(
                    "Falha no teste de equivalência",
                    object_name=obj.name,
                    difference=equivalence_result.difference
                )
                return ValidationResult(
                    object=obj,
                    status=ValidationStatus.FAILED,
                    syntax=syntax_result,
                    equivalence=equivalence_result,
                    error_message="Expressões não são numericamente equivalentes"
                )
        
        # 3. Análise de performance (se não skipada)
        performance_result = None
        if not skip_performance and self._mcp_client:
            performance_result = await self._performance_analyzer.analyze_performance(
                original_expression=refactor_item.original_expression,
                refactored_expression=refactor_item.refactored_expression,
                object_name=obj.name
            )
            
            if not performance_result.is_acceptable:
                logger.warning(
                    "Performance não aceitável",
                    object_name=obj.name,
                    refactored_time_ms=performance_result.refactored_time_ms,
                    threshold_ms=performance_result.threshold_ms
                )
                # Não falha por performance, apenas avisa
        
        # Sucesso em todas as validações
        logger.info(
            "Validação concluída com sucesso",
            object_name=obj.name
        )
        
        return ValidationResult(
            object=obj,
            status=ValidationStatus.PASSED,
            syntax=syntax_result,
            equivalence=equivalence_result,
            performance=performance_result
        )
    
    async def validate_batch(
        self,
        refactor_result: RefactorResult,
        skip_equivalence: bool = False,
        skip_performance: bool = True,  # Performance é mais lenta
        stop_on_first_failure: bool = False
    ) -> RefactorResult:
        """
        Valida todos os itens de um resultado de refatoração.
        
        Args:
            refactor_result: Resultado de refatoração a validar.
            skip_equivalence: Se True, pula testes de equivalência.
            skip_performance: Se True, pula análises de performance.
            stop_on_first_failure: Se True, para na primeira falha.
            
        Returns:
            Resultado de refatoração atualizado com validações.
        """
        logger.info(
            "Validando batch de refatorações",
            total_items=len(refactor_result.items)
        )
        
        validated_items = []
        failures = 0
        
        for item in refactor_result.items:
            # Pula itens sem expressão refatorada
            if not item.refactored_expression:
                item.validation = ValidationResult(
                    object=item.object,
                    status=ValidationStatus.SKIPPED,
                    error_message="Sem expressão refatorada"
                )
                validated_items.append(item)
                continue
            
            # Valida o item
            validation = await self.validate(
                refactor_item=item,
                skip_equivalence=skip_equivalence,
                skip_performance=skip_performance
            )
            
            item.validation = validation
            validated_items.append(item)
            
            if validation.status == ValidationStatus.FAILED:
                failures += 1
                if stop_on_first_failure:
                    logger.warning(
                        "Parando validação após primeira falha",
                        object_name=item.object.name
                    )
                    break
        
        # Atualiza resultado
        refactor_result.items = validated_items
        
        logger.info(
            "Validação batch concluída",
            total=len(validated_items),
            failures=failures
        )
        
        return refactor_result
    
    def validate_syntax_only(
        self,
        expression: str
    ) -> ValidationResult:
        """
        Validação rápida apenas de sintaxe.
        
        Args:
            expression: Expressão DAX a validar.
            
        Returns:
            Resultado da validação.
        """
        syntax_result = self._syntax_validator.validate(expression)
        
        return ValidationResult(
            object=SemanticObject(
                name="__syntax_check__",
                object_type="measure",
                expression=expression
            ),
            status=ValidationStatus.PASSED if syntax_result.is_valid else ValidationStatus.FAILED,
            syntax=syntax_result,
            error_message=syntax_result.error_message if not syntax_result.is_valid else None
        )
    
    async def quick_validate(
        self,
        original_expression: str,
        refactored_expression: str
    ) -> bool:
        """
        Validação rápida (sintaxe + equivalência básica).
        
        Args:
            original_expression: Expressão original.
            refactored_expression: Expressão refatorada.
            
        Returns:
            True se válido, False caso contrário.
        """
        # Valida sintaxe
        syntax = self._syntax_validator.validate(refactored_expression)
        if not syntax.is_valid:
            return False
        
        # Testa equivalência se MCP disponível
        if self._mcp_client:
            equiv = await self._equivalence_tester.quick_test(
                original_expression,
                refactored_expression
            )
            return equiv
        
        return True
    
    def get_validation_summary(
        self,
        refactor_result: RefactorResult
    ) -> dict:
        """
        Gera um resumo das validações.
        
        Args:
            refactor_result: Resultado de refatoração com validações.
            
        Returns:
            Dicionário com estatísticas.
        """
        total = len(refactor_result.items)
        
        passed = sum(
            1 for item in refactor_result.items
            if item.validation and item.validation.status == ValidationStatus.PASSED
        )
        
        failed = sum(
            1 for item in refactor_result.items
            if item.validation and item.validation.status == ValidationStatus.FAILED
        )
        
        skipped = sum(
            1 for item in refactor_result.items
            if item.validation and item.validation.status == ValidationStatus.SKIPPED
        )
        
        pending = total - passed - failed - skipped
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pending": pending,
            "success_rate": f"{(passed / total * 100):.1f}%" if total > 0 else "N/A"
        }
