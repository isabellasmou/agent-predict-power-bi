"""
Módulo de Refatoração DAX.

Orquestra o processo de refatoração de expressões DAX
utilizando LLMs e engenharia de prompts.
"""

import asyncio
from typing import Optional

import structlog

from pbi_refactor_agent.config import LLMProvider, Settings, get_settings
from pbi_refactor_agent.models import (
    ChangeType,
    ImpactAnalysis,
    ImpactedObject,
    RefactorItem,
    RefactorResult,
    RefactorStatus,
)
from pbi_refactor_agent.refactor.llm_client import LLMClient
from pbi_refactor_agent.refactor.prompt_engine import PromptEngine

logger = structlog.get_logger(__name__)


class DAXRefactor:
    """
    Refatorador de expressões DAX com suporte a LLM.
    
    Coordena o processo de refatoração de múltiplas expressões
    DAX impactadas por uma mudança no modelo.
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        prompt_engine: Optional[PromptEngine] = None,
        settings: Optional[Settings] = None
    ):
        """
        Inicializa o refatorador.
        
        Args:
            llm_client: Cliente LLM (criado automaticamente se não fornecido).
            prompt_engine: Motor de prompts (criado automaticamente se não fornecido).
            settings: Configurações do agente.
        """
        self._settings = settings or get_settings()
        self._llm_client = llm_client
        self._prompt_engine = prompt_engine or PromptEngine()
        
        logger.info("DAXRefactor inicializado")
    
    async def refactor(
        self,
        impact_analysis: ImpactAnalysis,
        llm_provider: Optional[LLMProvider] = None,
        llm_model: Optional[str] = None,
        max_concurrent: int = 3
    ) -> RefactorResult:
        """
        Refatora todas as expressões impactadas.
        
        Args:
            impact_analysis: Análise de impacto da mudança.
            llm_provider: Provedor de LLM a utilizar.
            llm_model: Modelo de LLM específico.
            max_concurrent: Máximo de refatorações concorrentes.
            
        Returns:
            Resultado da refatoração.
        """
        from datetime import datetime
        
        start_time = datetime.now()
        
        logger.info(
            "Iniciando refatoração",
            change_type=impact_analysis.change_type.value,
            total_impacts=impact_analysis.total_impacted,
            llm_provider=llm_provider or self._settings.default_llm_provider.value
        )
        
        # Cria cliente LLM se necessário
        if self._llm_client is None:
            self._llm_client = LLMClient(
                provider=llm_provider,
                model=llm_model,
                settings=self._settings
            )
        
        # Coleta todos os objetos que precisam de refatoração
        objects_to_refactor = []
        
        for impact in impact_analysis.direct_impacts:
            if impact.original_expression:
                objects_to_refactor.append(impact)
        
        for impact in impact_analysis.cascade_impacts:
            if impact.original_expression and not impact.requires_manual_review:
                objects_to_refactor.append(impact)
        
        logger.info(
            "Objetos para refatoração identificados",
            count=len(objects_to_refactor)
        )
        
        # Processa refatorações
        items: list[RefactorItem] = []
        
        if objects_to_refactor:
            # Processa em lotes para controlar concorrência
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def refactor_with_semaphore(impact: ImpactedObject) -> RefactorItem:
                async with semaphore:
                    return await self._refactor_single(impact, impact_analysis)
            
            tasks = [
                refactor_with_semaphore(impact)
                for impact in objects_to_refactor
            ]
            
            items = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filtra exceções e converte para itens de erro
            processed_items = []
            for i, item in enumerate(items):
                if isinstance(item, Exception):
                    logger.error(
                        "Erro ao refatorar objeto",
                        object_name=objects_to_refactor[i].object.name,
                        error=str(item)
                    )
                    # Cria item de erro
                    error_item = RefactorItem(
                        object=objects_to_refactor[i].object,
                        original_expression=objects_to_refactor[i].original_expression or "",
                        refactored_expression="",
                        llm_provider=self._llm_client.provider,
                        llm_model=self._llm_client.model,
                        confidence_score=0.0
                    )
                    processed_items.append(error_item)
                else:
                    processed_items.append(item)
            
            items = processed_items
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Determina status geral
        successful = sum(1 for item in items if item.refactored_expression)
        failed = len(items) - successful
        
        if failed == 0 and successful > 0:
            status = RefactorStatus.COMPLETED
        elif successful > 0:
            status = RefactorStatus.COMPLETED  # Parcialmente bem-sucedido
        else:
            status = RefactorStatus.FAILED
        
        result = RefactorResult(
            impact_analysis=impact_analysis,
            status=status,
            items=items,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration
        )
        
        logger.info(
            "Refatoração concluída",
            status=status.value,
            total=len(items),
            successful=successful,
            failed=failed,
            duration_seconds=duration
        )
        
        return result
    
    async def _refactor_single(
        self,
        impact: ImpactedObject,
        analysis: ImpactAnalysis
    ) -> RefactorItem:
        """
        Refatora uma única expressão.
        
        Args:
            impact: Objeto impactado.
            analysis: Análise de impacto completa.
            
        Returns:
            Item de refatoração.
        """
        obj = impact.object
        
        logger.debug(
            "Refatorando objeto",
            object_name=obj.name,
            object_type=obj.object_type
        )
        
        # Constrói o prompt apropriado
        prompt = self._build_prompt_for_change(impact, analysis)
        
        # Chama o LLM
        try:
            response = await self._llm_client.complete(
                prompt=prompt,
                system_prompt=self._prompt_engine.get_system_prompt(),
                temperature=0.0  # Determinístico para refatoração
            )
            
            # Valida a resposta
            is_valid, error_msg = self._prompt_engine.validate_response(response)
            
            if not is_valid:
                logger.warning(
                    "Resposta inválida do LLM",
                    object_name=obj.name,
                    error=error_msg
                )
                refactored_expression = ""
                confidence = 0.0
            else:
                refactored_expression = self._prompt_engine.extract_dax_from_response(response) or ""
                confidence = self._calculate_confidence(
                    impact.original_expression or "",
                    refactored_expression
                )
            
        except Exception as e:
            logger.error(
                "Erro ao chamar LLM",
                object_name=obj.name,
                error=str(e)
            )
            refactored_expression = ""
            confidence = 0.0
        
        return RefactorItem(
            object=obj,
            original_expression=impact.original_expression or "",
            refactored_expression=refactored_expression,
            llm_provider=self._llm_client.provider,
            llm_model=self._llm_client.model,
            confidence_score=confidence
        )
    
    def _build_prompt_for_change(
        self,
        impact: ImpactedObject,
        analysis: ImpactAnalysis
    ) -> str:
        """
        Constrói o prompt adequado para o tipo de mudança.
        
        Args:
            impact: Objeto impactado.
            analysis: Análise de impacto.
            
        Returns:
            Prompt construído.
        """
        change_type = analysis.change_type
        target = analysis.target_object
        new_value = analysis.new_value or ""
        
        if change_type == ChangeType.RENAME_COLUMN:
            return self._prompt_engine.build_rename_column_prompt(
                impacted_object=impact,
                table_name=target.table_name or "",
                old_name=target.name,
                new_name=new_value
            )
        
        elif change_type == ChangeType.RENAME_TABLE:
            return self._prompt_engine.build_rename_table_prompt(
                impacted_object=impact,
                old_table_name=target.name,
                new_table_name=new_value
            )
        
        elif change_type == ChangeType.RENAME_MEASURE:
            return self._prompt_engine.build_rename_measure_prompt(
                impacted_object=impact,
                old_measure_name=target.name,
                new_measure_name=new_value
            )
        
        else:
            # Fallback para refatoração genérica
            changes_description = f"Tipo de mudança: {change_type.value}\n"
            changes_description += f"Objeto alvo: {target.full_name}\n"
            if new_value:
                changes_description += f"Novo valor: {new_value}"
            
            return self._prompt_engine.build_general_refactor_prompt(
                impacted_object=impact,
                changes_description=changes_description
            )
    
    def _calculate_confidence(
        self,
        original: str,
        refactored: str
    ) -> float:
        """
        Calcula um score de confiança para a refatoração.
        
        Args:
            original: Expressão original.
            refactored: Expressão refatorada.
            
        Returns:
            Score de confiança entre 0 e 1.
        """
        if not refactored:
            return 0.0
        
        # Heurísticas simples de confiança
        confidence = 1.0
        
        # Penaliza se a estrutura mudou muito
        original_len = len(original)
        refactored_len = len(refactored)
        
        if original_len > 0:
            len_ratio = refactored_len / original_len
            if len_ratio < 0.5 or len_ratio > 2.0:
                confidence *= 0.7
        
        # Penaliza se keywords importantes desapareceram
        important_keywords = ["CALCULATE", "FILTER", "SUM", "AVERAGE", "VAR", "RETURN"]
        
        for keyword in important_keywords:
            if keyword in original.upper() and keyword not in refactored.upper():
                confidence *= 0.8
        
        # Penaliza se há muito menos referências a colunas
        original_refs = original.count("[")
        refactored_refs = refactored.count("[")
        
        if original_refs > 0 and refactored_refs < original_refs * 0.5:
            confidence *= 0.7
        
        return max(0.0, min(1.0, confidence))
    
    async def refactor_single_expression(
        self,
        expression: str,
        changes_description: str,
        context: Optional[dict] = None,
        llm_provider=None,
        llm_model: Optional[str] = None,
    ) -> tuple[str, float]:
        """
        Refatora uma única expressão DAX de forma standalone.
        
        Args:
            expression: Expressão DAX original.
            changes_description: Descrição das mudanças a aplicar.
            context: Contexto adicional (object_name, object_type, etc.).
            llm_provider: Provedor LLM opcional.
            llm_model: Modelo LLM opcional.
            
        Returns:
            Tupla (expressão_refatorada, confidence_score).
        """
        from pbi_refactor_agent.models import ObjectType, SemanticObject
        
        # Cria objeto mock para usar o prompt engine
        context = context or {}
        mock_object = SemanticObject(
            name=context.get("object_name", "Expression"),
            object_type=ObjectType(context.get("object_type", "measure")),
            table_name=context.get("table_name"),
            expression=expression,
            description=context.get("description")
        )
        
        mock_impact = ImpactedObject(
            object=mock_object,
            impact_type="direct",
            original_expression=expression
        )
        
        # Cria cliente LLM com provedor especificado ou padrão
        client = LLMClient(
            provider=llm_provider,
            model=llm_model,
            settings=self._settings,
        ) if llm_provider else (self._llm_client or LLMClient(settings=self._settings))
        
        # Constrói prompt
        prompt = self._prompt_engine.build_general_refactor_prompt(
            impacted_object=mock_impact,
            changes_description=changes_description
        )
        
        try:
            response = await client.complete(
                prompt=prompt,
                system_prompt=self._prompt_engine.get_system_prompt(),
                temperature=0.0
            )
            
            is_valid, _ = self._prompt_engine.validate_response(response)
            
            if not is_valid:
                return "", 0.0
            
            refactored = self._prompt_engine.extract_dax_from_response(response) or ""
            confidence = self._calculate_confidence(expression, refactored)
            
            return refactored, confidence
            
        except Exception as e:
            logger.error("Erro ao refatorar expressão", error=str(e))
            return "", 0.0
