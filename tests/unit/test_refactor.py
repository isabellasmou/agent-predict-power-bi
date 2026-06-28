"""
Testes unitários para o módulo de refatoração com LLM.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pbi_refactor_agent.refactor import DAXRefactor, LLMClient, PromptEngine, DAXPromptTemplate
from pbi_refactor_agent.config import LLMProvider


class TestPromptEngine:
    """Testes para PromptEngine."""
    
    @pytest.fixture
    def engine(self):
        """Cria engine de prompts."""
        return PromptEngine()
    
    def test_build_prompt_column_rename(self, engine):
        """Testa construção de prompt para renomeio de coluna."""
        prompt = engine.build_prompt(
            template=DAXPromptTemplate.RENAME_COLUMN,
            expression="SUM('Sales'[Amount])",
            table_name="Sales",
            old_name="Amount",
            new_name="TotalAmount",
            object_name="Total Sales",
            object_type="measure",
            description="Soma total de vendas"
        )
        
        assert "Amount" in prompt
        assert "TotalAmount" in prompt
        assert "Sales" in prompt
    
    def test_build_prompt_table_rename(self, engine):
        """Testa construção de prompt para renomeio de tabela."""
        prompt = engine.build_prompt(
            template=DAXPromptTemplate.RENAME_TABLE,
            expression="CALCULATE(SUM('Sales'[Amount]), 'Sales'[Region] = \"North\")",
            old_table_name="Sales",
            new_table_name="SalesData",
            object_name="Filtered Sales",
            object_type="measure"
        )
        
        assert "Sales" in prompt
        assert "SalesData" in prompt
    
    def test_extract_dax_simple(self, engine):
        """Testa extração de DAX de resposta simples."""
        response = "<dax>SUM('Sales'[TotalAmount])</dax>"
        result = engine.extract_dax_from_response(response)
        
        assert result == "SUM('Sales'[TotalAmount])"
    
    def test_extract_dax_with_markdown(self, engine):
        """Testa extração de DAX com markdown."""
        response = """
        Here is the refactored expression:
        
        <dax>
        SUM('Sales'[TotalAmount])
        </dax>
        
        This change updates the column reference.
        """
        result = engine.extract_dax_from_response(response)
        
        assert "SUM('Sales'[TotalAmount])" in result.strip()
    
    def test_get_system_prompt(self, engine):
        """Testa obtenção do system prompt."""
        system_prompt = engine.get_system_prompt()
        
        assert "DAX" in system_prompt
        assert "refatorar" in system_prompt.lower() or "Power BI" in system_prompt


class TestLLMClient:
    """Testes para LLMClient."""
    
    @pytest.fixture
    def mock_settings(self):
        """Settings mockadas."""
        settings = MagicMock()
        settings.default_llm_provider = LLMProvider.OPENAI
        settings.default_llm_model = "gpt-4o"
        settings.get_llm_api_key = MagicMock(return_value="test-key")
        return settings
    
    @pytest.mark.asyncio
    async def test_complete_with_openai(self, mock_settings):
        """Testa completação com OpenAI mockado."""
        with patch("pbi_refactor_agent.refactor.llm_client.OpenAIClient") as MockOpenAI:
            # Configura o mock do cliente OpenAI
            mock_openai_instance = AsyncMock()
            mock_openai_instance.complete = AsyncMock(return_value="SUM('Sales'[NewAmount])")
            MockOpenAI.return_value = mock_openai_instance
            
            client = LLMClient(settings=mock_settings)
            result = await client.complete("Test prompt")
            
            assert result == "SUM('Sales'[NewAmount])"
            mock_openai_instance.complete.assert_called_once()


class TestDAXRefactor:
    """Testes para DAXRefactor."""
    
    @pytest.fixture
    def mock_llm_client(self):
        """LLM Client mockado."""
        client = AsyncMock()
        client.complete = AsyncMock(return_value="<dax>SUM('Sales'[NewColumn])</dax>")
        return client
    
    @pytest.fixture
    def mock_prompt_engine(self):
        """PromptEngine mockado."""
        engine = MagicMock()
        engine.get_system_prompt = MagicMock(return_value="System prompt")
        engine.build_general_refactor_prompt = MagicMock(return_value="Refactor prompt")
        engine.extract_dax_from_response = MagicMock(return_value="SUM('Sales'[NewColumn])")
        engine.validate_response = MagicMock(return_value=(True, None))
        return engine
    
    @pytest.mark.asyncio
    async def test_refactor_single_expression(self, mock_llm_client, mock_prompt_engine):
        """Testa refatoração de expressão única."""
        refactor = DAXRefactor(
            llm_client=mock_llm_client,
            prompt_engine=mock_prompt_engine
        )
        
        result, confidence = await refactor.refactor_single_expression(
            expression="SUM('Sales'[OldColumn])",
            changes_description="Renomear coluna OldColumn para NewColumn",
            context={"object_name": "Total", "object_type": "measure"}
        )
        
        assert result == "SUM('Sales'[NewColumn])"
        assert confidence >= 0.0
    
    def test_dax_refactor_initialization(self):
        """Testa inicialização do DAXRefactor."""
        refactor = DAXRefactor()
        
        assert refactor._prompt_engine is not None
        # llm_client é criado sob demanda
        assert refactor._llm_client is None
