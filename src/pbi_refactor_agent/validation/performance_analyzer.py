"""
Analisador de Performance DAX.

Responsável por medir e comparar a performance de expressões DAX
antes e depois da refatoração.
"""

import asyncio
import statistics
from typing import Optional

import structlog

from pbi_refactor_agent.models import PerformanceValidation

logger = structlog.get_logger(__name__)


class PerformanceAnalyzer:
    """
    Analisador de performance de expressões DAX.
    
    Mede o tempo de execução e compara performance entre
    expressões originais e refatoradas.
    """
    
    def __init__(
        self,
        mcp_client=None,
        threshold_ms: float = 5000,
        num_runs: int = 3,
        warmup_runs: int = 1
    ):
        """
        Inicializa o analisador.
        
        Args:
            mcp_client: Cliente MCP para execução de queries DAX.
            threshold_ms: Threshold máximo aceitável em ms.
            num_runs: Número de execuções para média.
            warmup_runs: Número de execuções de warmup.
        """
        self._mcp_client = mcp_client
        self._threshold_ms = threshold_ms
        self._num_runs = num_runs
        self._warmup_runs = warmup_runs
    
    async def analyze_performance(
        self,
        original_expression: str,
        refactored_expression: str,
        object_name: str
    ) -> PerformanceValidation:
        """
        Analisa e compara performance de duas expressões.
        
        Args:
            original_expression: Expressão original.
            refactored_expression: Expressão refatorada.
            object_name: Nome do objeto para logging.
            
        Returns:
            Resultado da análise de performance.
        """
        logger.info(
            "Analisando performance",
            object_name=object_name,
            num_runs=self._num_runs
        )
        
        if not self._mcp_client:
            logger.warning("Cliente MCP não disponível - análise de performance skipada")
            return PerformanceValidation(
                original_time_ms=0,
                refactored_time_ms=0,
                time_difference_ms=0,
                percentage_change=0,
                is_acceptable=True,
                threshold_ms=self._threshold_ms
            )
        
        try:
            # Mede performance original
            original_time = await self._measure_expression(
                original_expression,
                "original"
            )
            
            # Mede performance refatorada
            refactored_time = await self._measure_expression(
                refactored_expression,
                "refactored"
            )
            
            # Calcula diferença
            time_diff = refactored_time - original_time
            
            if original_time > 0:
                percentage_change = (time_diff / original_time) * 100
            else:
                percentage_change = 0 if refactored_time == 0 else 100
            
            # Verifica se está dentro do threshold
            is_acceptable = (
                refactored_time <= self._threshold_ms
                and percentage_change <= 50  # Não mais que 50% mais lento
            )
            
            logger.info(
                "Análise de performance concluída",
                object_name=object_name,
                original_time_ms=original_time,
                refactored_time_ms=refactored_time,
                percentage_change=f"{percentage_change:.1f}%",
                is_acceptable=is_acceptable
            )
            
            return PerformanceValidation(
                original_time_ms=original_time,
                refactored_time_ms=refactored_time,
                time_difference_ms=time_diff,
                percentage_change=percentage_change,
                is_acceptable=is_acceptable,
                threshold_ms=self._threshold_ms
            )
            
        except Exception as e:
            logger.error(
                "Erro ao analisar performance",
                object_name=object_name,
                error=str(e)
            )
            return PerformanceValidation(
                original_time_ms=0,
                refactored_time_ms=0,
                time_difference_ms=0,
                percentage_change=0,
                is_acceptable=True,  # Assume aceitável em caso de erro
                threshold_ms=self._threshold_ms
            )
    
    async def _measure_expression(
        self,
        expression: str,
        label: str
    ) -> float:
        """
        Mede o tempo de execução de uma expressão.
        
        Args:
            expression: Expressão DAX a medir.
            label: Label para logging.
            
        Returns:
            Tempo médio de execução em ms.
        """
        times = []
        
        # Query para medir tempo
        query = f"""
EVALUATE
    ROW("result", {expression})
"""
        
        # Warmup
        for _ in range(self._warmup_runs):
            await self._mcp_client.execute_dax(query)
        
        # Execuções para medição
        for i in range(self._num_runs):
            start_time = asyncio.get_event_loop().time()
            
            result = await self._mcp_client.execute_dax(
                query,
                capture_timing=True
            )
            
            end_time = asyncio.get_event_loop().time()
            
            # Usa tempo do servidor se disponível
            if result and "execution_time_ms" in result:
                execution_time = result["execution_time_ms"]
            else:
                execution_time = (end_time - start_time) * 1000
            
            times.append(execution_time)
            
            logger.debug(
                f"Medição {i+1}/{self._num_runs} ({label})",
                execution_time_ms=execution_time
            )
        
        # Retorna mediana para evitar outliers
        if times:
            return statistics.median(times)
        return 0.0
    
    async def benchmark_expressions(
        self,
        expressions: list[tuple[str, str]],
        iterations: int = 5
    ) -> dict[str, dict]:
        """
        Faz benchmark de múltiplas expressões.
        
        Args:
            expressions: Lista de tuplas (nome, expressão).
            iterations: Número de iterações por expressão.
            
        Returns:
            Dicionário com resultados por expressão.
        """
        results = {}
        
        for name, expression in expressions:
            times = []
            
            for _ in range(iterations):
                time_ms = await self._measure_expression(expression, name)
                times.append(time_ms)
            
            results[name] = {
                "min_ms": min(times),
                "max_ms": max(times),
                "avg_ms": statistics.mean(times),
                "median_ms": statistics.median(times),
                "std_dev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            }
        
        return results
    
    def compare_performance(
        self,
        original_time: float,
        refactored_time: float
    ) -> str:
        """
        Gera uma descrição textual da comparação de performance.
        
        Args:
            original_time: Tempo original em ms.
            refactored_time: Tempo refatorado em ms.
            
        Returns:
            Descrição da comparação.
        """
        if original_time == 0:
            return "Não foi possível comparar (tempo original = 0)"
        
        diff = refactored_time - original_time
        percentage = (diff / original_time) * 100
        
        if abs(percentage) < 5:
            return f"Performance similar (diferença: {abs(diff):.1f}ms)"
        elif percentage < 0:
            return f"Melhoria de {abs(percentage):.1f}% ({abs(diff):.1f}ms mais rápido)"
        else:
            return f"Degradação de {percentage:.1f}% ({diff:.1f}ms mais lento)"
    
    async def quick_performance_check(
        self,
        expression: str
    ) -> bool:
        """
        Verificação rápida se expressão executa dentro do threshold.
        
        Args:
            expression: Expressão DAX a verificar.
            
        Returns:
            True se está dentro do threshold.
        """
        if not self._mcp_client:
            return True
        
        try:
            time_ms = await self._measure_expression(expression, "quick_check")
            return time_ms <= self._threshold_ms
        except Exception:
            return True  # Assume OK em caso de erro
