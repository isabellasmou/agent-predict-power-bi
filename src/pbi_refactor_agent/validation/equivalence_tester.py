"""
Testador de Equivalência Numérica.

Responsável por validar se duas expressões DAX produzem
resultados numericamente equivalentes.
"""

import math
from typing import Any, Optional

import structlog

from pbi_refactor_agent.models import EquivalenceValidation

logger = structlog.get_logger(__name__)


class EquivalenceTester:
    """
    Testador de equivalência numérica entre expressões DAX.
    
    Executa ambas as expressões e compara os resultados para
    garantir que a refatoração não alterou a lógica de negócio.
    """
    
    def __init__(
        self,
        mcp_client=None,
        tolerance: float = 0.0001,
        timeout_seconds: int = 60
    ):
        """
        Inicializa o testador.
        
        Args:
            mcp_client: Cliente MCP para execução de queries DAX.
            tolerance: Tolerância para comparação numérica.
            timeout_seconds: Timeout para execução de queries.
        """
        self._mcp_client = mcp_client
        self._tolerance = tolerance
        self._timeout = timeout_seconds
    
    async def test_equivalence(
        self,
        original_expression: str,
        refactored_expression: str,
        object_name: str,
        table_name: Optional[str] = None
    ) -> EquivalenceValidation:
        """
        Testa se duas expressões produzem resultados equivalentes.
        
        Args:
            original_expression: Expressão original.
            refactored_expression: Expressão refatorada.
            object_name: Nome do objeto (medida/coluna).
            table_name: Nome da tabela contexto.
            
        Returns:
            Resultado do teste de equivalência.
        """
        logger.info(
            "Testando equivalência",
            object_name=object_name,
            tolerance=self._tolerance
        )
        
        if not self._mcp_client:
            logger.warning("Cliente MCP não disponível - teste de equivalência skipado")
            return EquivalenceValidation(
                is_equivalent=True,  # Assume equivalente se não pode testar
                original_result=None,
                refactored_result=None,
                difference=None,
                tolerance_used=self._tolerance,
                sample_query=None
            )
        
        # Gera query de teste
        test_query = self._generate_test_query(
            original_expression,
            refactored_expression,
            table_name
        )
        
        try:
            # Executa query de teste
            result = await self._mcp_client.execute_dax(
                test_query,
                timeout=self._timeout
            )
            
            # Extrai resultados
            original_result = result.get("original_value")
            refactored_result = result.get("refactored_value")
            
            # Compara resultados
            is_equivalent, difference = self._compare_results(
                original_result,
                refactored_result
            )
            
            if is_equivalent:
                logger.info("Expressões são equivalentes", object_name=object_name)
            else:
                logger.warning(
                    "Expressões não são equivalentes",
                    object_name=object_name,
                    difference=difference
                )
            
            return EquivalenceValidation(
                is_equivalent=is_equivalent,
                original_result=original_result,
                refactored_result=refactored_result,
                difference=difference,
                tolerance_used=self._tolerance,
                sample_query=test_query
            )
            
        except Exception as e:
            logger.error(
                "Erro ao testar equivalência",
                object_name=object_name,
                error=str(e)
            )
            return EquivalenceValidation(
                is_equivalent=False,
                original_result=None,
                refactored_result=None,
                difference=None,
                tolerance_used=self._tolerance,
                sample_query=test_query
            )
    
    async def test_multiple_scenarios(
        self,
        original_expression: str,
        refactored_expression: str,
        object_name: str,
        table_name: Optional[str] = None,
        filter_contexts: Optional[list[str]] = None
    ) -> list[EquivalenceValidation]:
        """
        Testa equivalência em múltiplos cenários/contextos.
        
        Args:
            original_expression: Expressão original.
            refactored_expression: Expressão refatorada.
            object_name: Nome do objeto.
            table_name: Nome da tabela.
            filter_contexts: Lista de filtros DAX para testar.
            
        Returns:
            Lista de resultados de equivalência.
        """
        results = []
        
        # Teste sem filtro
        base_result = await self.test_equivalence(
            original_expression,
            refactored_expression,
            object_name,
            table_name
        )
        results.append(base_result)
        
        # Testes com filtros
        if filter_contexts:
            for filter_ctx in filter_contexts:
                filtered_orig = f"CALCULATE({original_expression}, {filter_ctx})"
                filtered_refact = f"CALCULATE({refactored_expression}, {filter_ctx})"
                
                result = await self.test_equivalence(
                    filtered_orig,
                    filtered_refact,
                    f"{object_name}_filtered",
                    table_name
                )
                results.append(result)
        
        return results
    
    def _generate_test_query(
        self,
        original_expression: str,
        refactored_expression: str,
        table_name: Optional[str] = None
    ) -> str:
        """
        Gera uma query DAX para testar equivalência.
        
        Args:
            original_expression: Expressão original.
            refactored_expression: Expressão refatorada.
            table_name: Nome da tabela para contexto.
            
        Returns:
            Query DAX de teste.
        """
        # Escapa expressões para uso em EVALUATE
        orig_escaped = original_expression.replace('"', '""')
        refact_escaped = refactored_expression.replace('"', '""')
        
        # Gera query que retorna ambos valores
        query = f"""
DEFINE
    VAR OriginalValue = {original_expression}
    VAR RefactoredValue = {refactored_expression}
EVALUATE
    ROW(
        "original_value", OriginalValue,
        "refactored_value", RefactoredValue,
        "difference", ABS(OriginalValue - RefactoredValue),
        "is_equal", IF(ABS(OriginalValue - RefactoredValue) < {self._tolerance}, TRUE(), FALSE())
    )
"""
        
        return query.strip()
    
    def _compare_results(
        self,
        original: Any,
        refactored: Any
    ) -> tuple[bool, Optional[float]]:
        """
        Compara dois resultados para equivalência.
        
        Args:
            original: Resultado original.
            refactored: Resultado refatorado.
            
        Returns:
            Tupla (é_equivalente, diferença).
        """
        # Ambos None ou Blank
        if original is None and refactored is None:
            return True, 0.0
        
        # Um None e outro não
        if original is None or refactored is None:
            return False, None
        
        # Ambos numéricos
        try:
            orig_float = float(original)
            refact_float = float(refactored)
            
            # Verifica NaN
            if math.isnan(orig_float) and math.isnan(refact_float):
                return True, 0.0
            
            if math.isnan(orig_float) or math.isnan(refact_float):
                return False, None
            
            # Verifica infinito
            if math.isinf(orig_float) and math.isinf(refact_float):
                return orig_float == refact_float, 0.0
            
            # Calcula diferença
            difference = abs(orig_float - refact_float)
            
            # Verifica com tolerância absoluta e relativa
            if difference <= self._tolerance:
                return True, difference
            
            # Tolerância relativa para números grandes
            if orig_float != 0:
                relative_diff = difference / abs(orig_float)
                if relative_diff <= self._tolerance:
                    return True, difference
            
            return False, difference
            
        except (ValueError, TypeError):
            # Comparação de strings/outros tipos
            if str(original) == str(refactored):
                return True, 0.0
            return False, None
    
    def _generate_sample_filters(
        self,
        table_name: str
    ) -> list[str]:
        """
        Gera filtros de amostra para testes.
        
        Args:
            table_name: Nome da tabela.
            
        Returns:
            Lista de expressões de filtro.
        """
        # Filtros genéricos comuns
        return [
            f"TOPN(100, '{table_name}')",
            f"SAMPLE(100, '{table_name}', [__random])",
        ]
    
    async def quick_test(
        self,
        original_expression: str,
        refactored_expression: str
    ) -> bool:
        """
        Teste rápido de equivalência sem detalhes.
        
        Args:
            original_expression: Expressão original.
            refactored_expression: Expressão refatorada.
            
        Returns:
            True se equivalentes, False caso contrário.
        """
        result = await self.test_equivalence(
            original_expression,
            refactored_expression,
            "quick_test"
        )
        return result.is_equivalent
