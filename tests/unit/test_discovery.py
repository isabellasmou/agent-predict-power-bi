"""
Testes unitários para o módulo de descoberta de dependências.
"""

import pytest
from pbi_refactor_agent.discovery import DependencyGraph, ImpactAnalyzer
from pbi_refactor_agent.models import (
    CalculatedColumnInfo,
    ChangeType,
    ColumnInfo,
    MeasureInfo,
    ObjectType,
    ProposedChange,
    RelationshipInfo,
    TableInfo,
)


class TestDependencyGraph:
    """Testes para DependencyGraph."""
    
    @pytest.fixture
    def graph(self):
        """Cria um grafo para testes."""
        return DependencyGraph()
    
    @pytest.fixture
    def sample_table(self):
        """Tabela de exemplo."""
        return TableInfo(
            name="Sales",
            columns=["OrderID", "ProductID", "Quantity", "Amount"],
            measures=["Total Sales", "Total Quantity"],
        )
    
    @pytest.fixture
    def sample_column(self):
        """Coluna de exemplo."""
        return ColumnInfo(
            name="Amount",
            table_name="Sales",
            data_type="decimal",
        )
    
    @pytest.fixture
    def sample_measure(self):
        """Medida de exemplo."""
        return MeasureInfo(
            name="Total Sales",
            table_name="Sales",
            expression="SUM('Sales'[Amount])",
        )
    
    def test_add_table(self, graph, sample_table):
        """Testa adição de tabela ao grafo."""
        graph.add_table(sample_table)
        
        assert graph.node_count == 1
        assert sample_table.name in [t.name for t in graph._tables.values()]
    
    def test_add_column(self, graph, sample_table, sample_column):
        """Testa adição de coluna ao grafo."""
        graph.add_table(sample_table)
        graph.add_column(sample_column)
        
        assert graph.node_count == 2
    
    def test_add_measure(self, graph, sample_table, sample_column, sample_measure):
        """Testa adição de medida com análise de dependências."""
        graph.add_table(sample_table)
        graph.add_column(sample_column)
        graph.add_measure(sample_measure)
        
        assert graph.node_count == 3
        # Verifica se a dependência foi criada
        assert graph.edge_count >= 1
    
    def test_find_by_name(self, graph, sample_table, sample_column):
        """Testa busca de objeto por nome."""
        graph.add_table(sample_table)
        graph.add_column(sample_column)
        
        found = graph.find_by_name("Amount", table_name="Sales")
        assert found is not None
        assert found.name == "Amount"
    
    def test_find_objects_referencing(self, graph, sample_table, sample_column, sample_measure):
        """Testa busca de objetos que referenciam uma coluna."""
        graph.add_table(sample_table)
        graph.add_column(sample_column)
        graph.add_measure(sample_measure)
        
        referencing = graph.find_objects_referencing("Sales", "Amount")
        assert len(referencing) >= 1
        assert any(obj.name == "Total Sales" for obj in referencing)


class TestImpactAnalyzer:
    """Testes para ImpactAnalyzer."""
    
    @pytest.fixture
    def analyzer_with_model(self):
        """Cria analyzer com modelo de exemplo."""
        graph = DependencyGraph()
        
        # Adiciona tabela
        table = TableInfo(name="Sales", columns=["Amount", "Quantity"])
        graph.add_table(table)
        
        # Adiciona colunas
        col1 = ColumnInfo(name="Amount", table_name="Sales", data_type="decimal")
        col2 = ColumnInfo(name="Quantity", table_name="Sales", data_type="int")
        graph.add_column(col1)
        graph.add_column(col2)
        
        # Adiciona medidas
        measure1 = MeasureInfo(
            name="Total Sales",
            table_name="Sales",
            expression="SUM('Sales'[Amount])"
        )
        measure2 = MeasureInfo(
            name="Revenue per Unit",
            table_name="Sales",
            expression="DIVIDE([Total Sales], SUM('Sales'[Quantity]))"
        )
        graph.add_measure(measure1)
        graph.add_measure(measure2)
        
        return ImpactAnalyzer(graph)
    
    def test_analyze_column_rename(self, analyzer_with_model):
        """Testa análise de impacto para renomeio de coluna."""
        change = ProposedChange(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount"
        )
        
        impact = analyzer_with_model.analyze(change)
        
        assert impact.change_type == ChangeType.RENAME_COLUMN
        assert impact.new_value == "TotalAmount"
        # Deve encontrar a medida Total Sales como impactada
        assert impact.total_impacted >= 1
    
    def test_analyze_returns_suggested_expression(self, analyzer_with_model):
        """Testa se a análise retorna expressão sugerida."""
        change = ProposedChange(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount"
        )
        
        impact = analyzer_with_model.analyze(change)
        
        # Verifica se há expressão sugerida nos impactos diretos
        for direct_impact in impact.direct_impacts:
            if direct_impact.object.name == "Total Sales":
                assert "TotalAmount" in (direct_impact.suggested_expression or "")


class TestSyntaxValidator:
    """Testes para validador de sintaxe."""
    
    def test_valid_simple_expression(self):
        """Testa expressão simples válida."""
        from pbi_refactor_agent.validation import SyntaxValidator
        
        validator = SyntaxValidator()
        result = validator.validate("SUM('Sales'[Amount])")
        
        assert result.is_valid
    
    def test_unbalanced_brackets(self):
        """Testa detecção de colchetes desbalanceados."""
        from pbi_refactor_agent.validation import SyntaxValidator
        
        validator = SyntaxValidator()
        result = validator.validate("SUM('Sales'[Amount)")
        
        assert not result.is_valid
        assert "colchetes" in result.error_message.lower() or "brackets" in result.error_message.lower()
    
    def test_unbalanced_parentheses(self):
        """Testa detecção de parênteses desbalanceados."""
        from pbi_refactor_agent.validation import SyntaxValidator
        
        validator = SyntaxValidator()
        result = validator.validate("CALCULATE(SUM('Sales'[Amount])")
        
        assert not result.is_valid
    
    def test_var_without_return(self):
        """Testa detecção de VAR sem RETURN."""
        from pbi_refactor_agent.validation import SyntaxValidator
        
        validator = SyntaxValidator()
        result = validator.validate("VAR x = 1")
        
        assert not result.is_valid
        assert "RETURN" in result.error_message.upper()
    
    def test_valid_var_return(self):
        """Testa expressão VAR/RETURN válida."""
        from pbi_refactor_agent.validation import SyntaxValidator
        
        validator = SyntaxValidator()
        result = validator.validate("""
            VAR TotalSales = SUM('Sales'[Amount])
            RETURN TotalSales * 1.1
        """)
        
        assert result.is_valid
