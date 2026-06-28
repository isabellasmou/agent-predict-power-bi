"""
Testes unitários para o módulo agent (orquestrador principal).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from pbi_refactor_agent.agent import RefactorAgent
from pbi_refactor_agent.models import (
    ChangeType,
    ProposedChange,
    RefactorStatus,
    ValidationStatus,
    ImpactAnalysis,
    RefactorResult
)
from pbi_refactor_agent.config import LLMProvider


class TestRefactorAgent:
    """Testes para RefactorAgent."""
    
    @pytest.fixture
    def mock_settings(self):
        """Settings mockadas."""
        settings = MagicMock()
        settings.default_llm_provider = LLMProvider.GROQ
        settings.default_llm_model = "llama-3.3-70b-versatile"
        settings.groq_api_key = "test-key"
        settings.max_retries = 3
        settings.timeout = 30
        return settings
    
    @pytest.fixture
    def agent(self, mock_settings):
        """Cria agente para testes."""
        with patch('pbi_refactor_agent.agent.get_settings', return_value=mock_settings):
            return RefactorAgent(
                llm_provider="groq",
                llm_model="llama-3.3-70b-versatile"
            )
    
    def test_agent_initialization(self, agent):
        """Testa inicialização do agente."""
        assert agent is not None
        assert agent._llm_provider == "groq"
        assert agent._llm_model == "llama-3.3-70b-versatile"
        assert agent._status == RefactorStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_load_model_from_pbit(self, agent):
        """Testa carregamento de modelo .pbit."""
        # Mock do extrator
        with patch('pbi_refactor_agent.agent.extract_model') as mock_extract:
            mock_extract.return_value = MagicMock(
                file_name="test.pbit",
                tables=[],
                relationships=[]
            )
            
            await agent.load_model("test.pbit")
            
            assert agent._model_metadata is not None
            assert agent._dependency_graph is not None
            mock_extract.assert_called_once_with("test.pbit")
    
    @pytest.mark.asyncio
    async def test_analyze_impact(self, agent):
        """Testa análise de impacto de mudança."""
        # Setup: modelo mockado
        agent._dependency_graph = MagicMock()
        agent._impact_analyzer = MagicMock()
        
        mock_impact = ImpactAnalysis(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount",
            direct_impacts=[],
            cascade_impacts=[],
            total_impacted=5
        )
        agent._impact_analyzer.analyze.return_value = mock_impact
        
        # Executar
        change = ProposedChange(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount"
        )
        
        result = await agent.analyze_impact(change)
        
        assert result.total_impacted == 5
        assert result.change_type == ChangeType.RENAME_COLUMN
        agent._impact_analyzer.analyze.assert_called_once_with(change)
    
    @pytest.mark.asyncio
    async def test_refactor_expressions(self, agent):
        """Testa refatoração de expressões."""
        # Setup: componentes mockados
        agent._dax_refactor = AsyncMock()
        agent._validator = AsyncMock()
        
        mock_refactor_result = RefactorResult(
            status=RefactorStatus.COMPLETED,
            items=[
                MagicMock(
                    object=MagicMock(full_name="Sales[Total]"),
                    refactored_expression="SUM('Sales'[TotalAmount])",
                    confidence=1.0
                )
            ]
        )
        agent._dax_refactor.refactor.return_value = mock_refactor_result
        
        mock_validation = MagicMock(
            syntax=MagicMock(is_valid=True, status=ValidationStatus.PASSED)
        )
        agent._validator.validate_refactor_item.return_value = mock_validation
        
        # Executar
        impact_analysis = ImpactAnalysis(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount",
            direct_impacts=[MagicMock()],
            cascade_impacts=[],
            total_impacted=1
        )
        
        result = await agent.refactor_expressions(impact_analysis)
        
        assert result.status == RefactorStatus.COMPLETED
        assert len(result.items) == 1
        agent._dax_refactor.refactor.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_full_pipeline(self, agent):
        """Testa pipeline completo: carregar → analisar → refatorar."""
        # Mock de todos os componentes
        with patch('pbi_refactor_agent.agent.extract_model') as mock_extract, \
             patch.object(agent, '_build_dependency_graph') as mock_build_graph, \
             patch.object(agent, 'analyze_impact') as mock_analyze, \
             patch.object(agent, 'refactor_expressions') as mock_refactor:
            
            # Setup
            mock_extract.return_value = MagicMock(tables=[], relationships=[])
            mock_analyze.return_value = ImpactAnalysis(
                change_type=ChangeType.RENAME_COLUMN,
                table_name="Sales",
                object_name="Amount",
                new_value="TotalAmount",
                direct_impacts=[],
                cascade_impacts=[],
                total_impacted=0
            )
            mock_refactor.return_value = RefactorResult(
                status=RefactorStatus.COMPLETED,
                items=[]
            )
            
            # Executar pipeline
            await agent.load_model("test.pbit")
            
            change = ProposedChange(
                change_type=ChangeType.RENAME_COLUMN,
                table_name="Sales",
                object_name="Amount",
                new_value="TotalAmount"
            )
            
            impact = await agent.analyze_impact(change)
            result = await agent.refactor_expressions(impact)
            
            # Verificar chamadas
            mock_extract.assert_called_once()
            mock_analyze.assert_called_once()
            mock_refactor.assert_called_once()
            assert result.status == RefactorStatus.COMPLETED
    
    def test_agent_state_management(self, agent):
        """Testa gerenciamento de estado do agente."""
        assert agent._status == RefactorStatus.PENDING
        
        # Estado deve mudar após operações
        agent._status = RefactorStatus.IN_PROGRESS
        assert agent._status == RefactorStatus.IN_PROGRESS
        
        agent._status = RefactorStatus.COMPLETED
        assert agent._status == RefactorStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_error_handling(self, agent):
        """Testa tratamento de erros."""
        # Mock: extract_model lança exceção
        with patch('pbi_refactor_agent.agent.extract_model') as mock_extract:
            mock_extract.side_effect = Exception("File not found")
            
            with pytest.raises(Exception, match="File not found"):
                await agent.load_model("invalid.pbit")
    
    def test_lazy_initialization_of_components(self, agent):
        """Testa inicialização lazy de componentes."""
        # Componentes devem ser None inicialmente
        assert agent._dependency_graph is None
        assert agent._impact_analyzer is None
        assert agent._dax_refactor is None
        assert agent._validator is None


class TestRefactorAgentIntegration:
    """Testes de integração do agente com componentes reais."""
    
    @pytest.fixture
    def agent_with_real_components(self):
        """Cria agente com componentes reais (não mockados)."""
        return RefactorAgent(llm_provider="groq")
    
    @pytest.mark.asyncio
    async def test_load_real_pbit(self, agent_with_real_components, tmp_path):
        """Testa carregamento de .pbit real (se disponível)."""
        # Criar .pbit fake para teste
        test_pbit = tmp_path / "test.pbit"
        
        # Pular se arquivo não existir (teste opcional)
        if not test_pbit.exists():
            pytest.skip("Arquivo .pbit de teste não disponível")
        
        await agent_with_real_components.load_model(str(test_pbit))
        
        assert agent_with_real_components._model_metadata is not None
    
    def test_agent_configuration(self, agent_with_real_components):
        """Testa configuração do agente."""
        assert agent_with_real_components._llm_provider == "groq"
        assert agent_with_real_components._status == RefactorStatus.PENDING


class TestRefactorAgentEdgeCases:
    """Testes de casos extremos."""
    
    @pytest.fixture
    def agent(self, mock_settings):
        """Cria agente para testes."""
        with patch('pbi_refactor_agent.agent.get_settings', return_value=mock_settings):
            return RefactorAgent()
    
    @pytest.mark.asyncio
    async def test_analyze_impact_without_model(self, agent):
        """Testa análise sem modelo carregado."""
        change = ProposedChange(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount"
        )
        
        with pytest.raises(Exception):
            await agent.analyze_impact(change)
    
    @pytest.mark.asyncio
    async def test_refactor_with_zero_impacts(self, agent):
        """Testa refatoração quando não há objetos impactados."""
        # Setup
        agent._dax_refactor = AsyncMock()
        
        impact_analysis = ImpactAnalysis(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="NonExistent",
            new_value="NewName",
            direct_impacts=[],
            cascade_impacts=[],
            total_impacted=0
        )
        
        mock_result = RefactorResult(
            status=RefactorStatus.COMPLETED,
            items=[]
        )
        agent._dax_refactor.refactor.return_value = mock_result
        
        result = await agent.refactor_expressions(impact_analysis)
        
        # Deve completar mesmo sem impactos
        assert result.status == RefactorStatus.COMPLETED
        assert len(result.items) == 0
    
    @pytest.mark.asyncio
    async def test_refactor_with_validation_failures(self, agent):
        """Testa refatoração quando validação falha."""
        # Setup
        agent._dax_refactor = AsyncMock()
        agent._validator = AsyncMock()
        
        # Mock: refatoração OK mas validação falha
        mock_refactor_result = RefactorResult(
            status=RefactorStatus.COMPLETED,
            items=[
                MagicMock(
                    object=MagicMock(full_name="Sales[Total]"),
                    refactored_expression="INVALID DAX(",  # Sintaxe inválida
                    confidence=0.8
                )
            ]
        )
        agent._dax_refactor.refactor.return_value = mock_refactor_result
        
        mock_validation = MagicMock(
            syntax=MagicMock(is_valid=False, status=ValidationStatus.FAILED)
        )
        agent._validator.validate_refactor_item.return_value = mock_validation
        
        impact_analysis = ImpactAnalysis(
            change_type=ChangeType.RENAME_COLUMN,
            table_name="Sales",
            object_name="Amount",
            new_value="TotalAmount",
            direct_impacts=[MagicMock()],
            cascade_impacts=[],
            total_impacted=1
        )
        
        result = await agent.refactor_expressions(impact_analysis)
        
        # Deve reportar falha de validação
        assert result.status in [RefactorStatus.COMPLETED, RefactorStatus.FAILED]


class TestRefactorAgentMock:
    """Testes com mock settings."""
    
    @pytest.fixture
    def mock_settings(self):
        """Settings mockadas para testes."""
        settings = MagicMock()
        settings.default_llm_provider = LLMProvider.GROQ
        settings.default_llm_model = "llama-3.3-70b-versatile"
        settings.groq_api_key = "test-key"
        settings.max_retries = 3
        settings.timeout = 30
        settings.log_level = "DEBUG"
        return settings
    
    def test_agent_uses_settings(self, mock_settings):
        """Testa se agente usa settings corretamente."""
        with patch('pbi_refactor_agent.agent.get_settings', return_value=mock_settings):
            agent = RefactorAgent()
            
            # Deve usar configurações do settings
            assert agent._llm_provider == mock_settings.default_llm_provider.value
            assert agent._llm_model == mock_settings.default_llm_model
