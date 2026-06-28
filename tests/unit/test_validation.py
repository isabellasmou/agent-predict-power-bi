"""
Testes unitários para o módulo de validação.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from pbi_refactor_agent.validation import (
    SyntaxValidator,
    EquivalenceTester,
    PerformanceAnalyzer,
    DAXValidator,
    AntiPatternDetector
)
from pbi_refactor_agent.models import (
    RefactorItem,
    SemanticObject,
    ValidationStatus
)


class TestSyntaxValidator:
    """Testes para SyntaxValidator."""
    
    @pytest.fixture
    def validator(self):
        """Cria validator para testes."""
        return SyntaxValidator()
    
    def test_valid_simple_expression(self, validator):
        """Testa expressão simples válida."""
        result = validator.validate("SUM('Sales'[Amount])")
        
        assert result.is_valid
        assert result.status == ValidationStatus.PASSED
        assert result.error_message is None
    
    def test_valid_calculate(self, validator):
        """Testa expressão CALCULATE válida."""
        expr = "CALCULATE(SUM('Sales'[Amount]), 'Sales'[Region] = \"North\")"
        result = validator.validate(expr)
        
        assert result.is_valid
    
    def test_unbalanced_parentheses(self, validator):
        """Testa detecção de parênteses desbalanceados."""
        result = validator.validate("CALCULATE(SUM('Sales'[Amount])")
        
        assert not result.is_valid
        assert result.status == ValidationStatus.FAILED
        assert "parênteses" in result.error_message.lower() or "parentheses" in result.error_message.lower()
    
    def test_unbalanced_brackets(self, validator):
        """Testa detecção de colchetes desbalanceados."""
        result = validator.validate("SUM('Sales'[Amount)")
        
        assert not result.is_valid
        assert "colchetes" in result.error_message.lower() or "brackets" in result.error_message.lower()
    
    def test_unbalanced_quotes(self, validator):
        """Testa detecção de aspas desbalanceadas."""
        result = validator.validate("CALCULATE(SUM('Sales[Amount]), 'Sales'[Region] = \"North)")
        
        assert not result.is_valid
    
    def test_var_without_return(self, validator):
        """Testa detecção de VAR sem RETURN."""
        result = validator.validate("VAR TotalSales = SUM('Sales'[Amount])")
        
        assert not result.is_valid
        assert "RETURN" in result.error_message.upper()
    
    def test_valid_var_return(self, validator):
        """Testa expressão VAR/RETURN válida."""
        expr = """
        VAR TotalSales = SUM('Sales'[Amount])
        VAR TotalQty = SUM('Sales'[Quantity])
        RETURN
            DIVIDE(TotalSales, TotalQty)
        """
        result = validator.validate(expr)
        
        assert result.is_valid
    
    def test_empty_expression(self, validator):
        """Testa expressão vazia."""
        result = validator.validate("")
        
        assert not result.is_valid
    
    def test_only_whitespace(self, validator):
        """Testa expressão com apenas espaços."""
        result = validator.validate("   \n  \t  ")
        
        assert not result.is_valid


class TestAntiPatternDetector:
    """Testes para AntiPatternDetector."""
    
    @pytest.fixture
    def detector(self):
        """Cria detector para testes."""
        return AntiPatternDetector()
    
    def test_no_anti_patterns(self, detector):
        """Testa expressão sem anti-patterns."""
        expr = "SUM('Sales'[Amount])"
        report = detector.detect(expr, object_name="Total Sales")
        
        assert len(report.findings) == 0
    
    def test_row_context_bleeding(self, detector):
        """Testa detecção de row context bleeding."""
        # FILTER com medida sem CALCULATE
        expr = "FILTER(ALL('Sales'), [Total Sales] > 1000)"
        report = detector.detect(expr, object_name="High Sales")
        
        # Deve detectar uso de medida em contexto de linha
        assert len(report.findings) > 0
    
    def test_unnecessary_calculate(self, detector):
        """Testa detecção de CALCULATE redundante."""
        expr = "CALCULATE(SUM('Sales'[Amount]), TRUE())"
        report = detector.detect(expr, object_name="Total Sales")
        
        # CALCULATE com TRUE() é redundante
        assert any(f.severity.value == 'warning' for f in report.findings)
    
    def test_improper_sumx(self, detector):
        """Testa detecção de SUMX impróprio."""
        # SUMX com medida simples poderia ser SUM
        expr = "SUMX('Sales', [Total Amount])"
        report = detector.detect(expr, object_name="Aggregated")
        
        # Sugere usar SUM direto
        assert len(report.findings) > 0


class TestEquivalenceTester:
    """Testes para EquivalenceTester."""
    
    @pytest.fixture
    def tester(self):
        """Cria tester com MCP mockado."""
        mock_mcp = MagicMock()
        mock_mcp.execute_dax = AsyncMock()
        return EquivalenceTester(mcp_client=mock_mcp)
    
    @pytest.mark.asyncio
    async def test_equivalent_expressions(self, tester):
        """Testa expressões equivalentes."""
        # Mock: ambas retornam 1000
        tester._mcp_client.execute_dax.side_effect = [1000.0, 1000.0]
        
        result = await tester.test_equivalence(
            original="SUM('Sales'[Amount])",
            refactored="SUM('Sales'[TotalAmount])"
        )
        
        assert result.is_equivalent
        assert result.status == ValidationStatus.PASSED
    
    @pytest.mark.asyncio
    async def test_non_equivalent_expressions(self, tester):
        """Testa expressões não-equivalentes."""
        # Mock: valores diferentes
        tester._mcp_client.execute_dax.side_effect = [1000.0, 1200.0]
        
        result = await tester.test_equivalence(
            original="SUM('Sales'[Amount])",
            refactored="SUM('Sales'[Quantity])"
        )
        
        assert not result.is_equivalent
        assert result.status == ValidationStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_numeric_tolerance(self, tester):
        """Testa tolerância numérica."""
        # Mock: valores com diferença < tolerância
        tester._mcp_client.execute_dax.side_effect = [1000.0, 1000.05]
        tester._tolerance = 0.001  # 0.1%
        
        result = await tester.test_equivalence(
            original="AVERAGE('Sales'[Amount])",
            refactored="AVERAGE('Sales'[TotalAmount])"
        )
        
        # Diferença de 0.005% deve passar
        assert result.is_equivalent
    
    @pytest.mark.asyncio
    async def test_mcp_error_handling(self, tester):
        """Testa tratamento de erro do MCP."""
        # Mock: erro ao executar
        tester._mcp_client.execute_dax.side_effect = Exception("Connection failed")
        
        result = await tester.test_equivalence(
            original="SUM('Sales'[Amount])",
            refactored="SUM('Sales'[TotalAmount])"
        )
        
        assert result.status == ValidationStatus.ERROR
        assert "Connection failed" in result.error_message


class TestPerformanceAnalyzer:
    """Testes para PerformanceAnalyzer."""
    
    @pytest.fixture
    def analyzer(self):
        """Cria analyzer com MCP mockado."""
        mock_mcp = MagicMock()
        mock_mcp.execute_dax_with_timing = AsyncMock()
        return PerformanceAnalyzer(mcp_client=mock_mcp)
    
    @pytest.mark.asyncio
    async def test_performance_measurement(self, analyzer):
        """Testa medição de performance."""
        # Mock: retorna tempos de execução
        analyzer._mcp_client.execute_dax_with_timing.side_effect = [
            (100.0, 50.0),  # valor, tempo (ms)
            (100.0, 48.0),
            (100.0, 52.0),
        ]
        
        result = await analyzer.analyze_performance(
            expression="SUM('Sales'[Amount])",
            runs=3
        )
        
        assert result.status == ValidationStatus.PASSED
        assert result.avg_execution_time_ms > 0
        assert result.min_time_ms == 48.0
        assert result.max_time_ms == 52.0
    
    @pytest.mark.asyncio
    async def test_performance_regression(self, analyzer):
        """Testa detecção de regressão de performance."""
        # Mock: versão refatorada é mais lenta
        analyzer._mcp_client.execute_dax_with_timing.side_effect = [
            (100.0, 50.0),   # original
            (100.0, 50.0),
            (100.0, 50.0),
            (100.0, 200.0),  # refatorada (4x mais lenta)
            (100.0, 200.0),
            (100.0, 200.0),
        ]
        
        result = await analyzer.compare_performance(
            original="SUM('Sales'[Amount])",
            refactored="CALCULATE(SUM('Sales'[TotalAmount]), ALL('Sales'))",
            runs=3
        )
        
        # Deve detectar degradação
        assert result.is_regression
        assert result.performance_delta_pct > 200  # 300% mais lento


class TestDAXValidator:
    """Testes para DAXValidator (orquestrador)."""
    
    @pytest.fixture
    def validator(self):
        """Cria validator completo."""
        return DAXValidator()
    
    @pytest.mark.asyncio
    async def test_validate_refactor_item(self, validator):
        """Testa validação completa de item refatorado."""
        item = RefactorItem(
            object=MagicMock(spec=SemanticObject, full_name="Sales[Total Sales]"),
            original_expression="SUM('Sales'[Amount])",
            refactored_expression="SUM('Sales'[TotalAmount])",
            confidence=0.95
        )
        
        result = await validator.validate_refactor_item(item)
        
        # Deve passar validação sintática
        assert result.syntax.status == ValidationStatus.PASSED
        # Equivalência e performance skipped (MCP não disponível)
        assert result.equivalence.status == ValidationStatus.SKIPPED
        assert result.performance.status == ValidationStatus.SKIPPED
    
    @pytest.mark.asyncio
    async def test_validate_invalid_syntax(self, validator):
        """Testa validação de sintaxe inválida."""
        item = RefactorItem(
            object=MagicMock(spec=SemanticObject, full_name="Sales[Total Sales]"),
            original_expression="SUM('Sales'[Amount])",
            refactored_expression="SUM('Sales'[TotalAmount)",  # Colchete não fechado
            confidence=0.95
        )
        
        result = await validator.validate_refactor_item(item)
        
        # Deve falhar na validação sintática
        assert result.syntax.status == ValidationStatus.FAILED
        assert not result.syntax.is_valid
    
    def test_get_validation_summary(self, validator):
        """Testa geração de resumo de validação."""
        # Mock de resultados
        results = [
            MagicMock(syntax=MagicMock(status=ValidationStatus.PASSED)),
            MagicMock(syntax=MagicMock(status=ValidationStatus.PASSED)),
            MagicMock(syntax=MagicMock(status=ValidationStatus.FAILED)),
        ]
        
        summary = validator.get_validation_summary(results)
        
        assert summary['total'] == 3
        assert summary['passed'] == 2
        assert summary['failed'] == 1
        assert summary['pass_rate'] == pytest.approx(66.67, rel=0.1)


class TestIntegration:
    """Testes de integração do módulo de validação."""
    
    @pytest.mark.asyncio
    async def test_full_validation_pipeline(self):
        """Testa pipeline completo de validação."""
        validator = DAXValidator()
        
        # Criar item refatorado válido
        item = RefactorItem(
            object=MagicMock(spec=SemanticObject, full_name="Sales[Total]"),
            original_expression="SUM('Sales'[Amount])",
            refactored_expression="SUM('Sales'[TotalAmount])",
            confidence=1.0
        )
        
        # Executar validação
        result = await validator.validate_refactor_item(item)
        
        # Sintaxe deve passar
        assert result.syntax.is_valid
        # Outros testes podem estar skipped se MCP não disponível
        assert result.syntax.status == ValidationStatus.PASSED
