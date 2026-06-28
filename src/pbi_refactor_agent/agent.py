"""
Agente de Refatoração Power BI.

Orquestra o fluxo completo de análise de impacto e refatoração
de modelos semânticos Power BI.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from pbi_refactor_agent.config import LLMProvider, Settings, get_settings
from pbi_refactor_agent.discovery import DependencyGraph, ImpactAnalyzer
from pbi_refactor_agent.mcp_client import MCPClient
from pbi_refactor_agent.models import (
    CalculatedColumnInfo,
    ChangeType,
    ColumnInfo,
    ImpactAnalysis,
    MeasureInfo,
    ProposedChange,
    RefactorResult,
    RefactorStatus,
)
from pbi_refactor_agent.refactor import DAXRefactor
from pbi_refactor_agent.validation import DAXValidator

logger = structlog.get_logger(__name__)


class RefactorAgent:
    """
    Agente principal para refatoração de modelos semânticos Power BI.
    
    Orquestra o fluxo completo:
    1. Descoberta de dependências
    2. Análise de impacto
    3. Refatoração com LLM
    4. Validação
    5. Aplicação em transação
    """
    
    def __init__(
        self,
        mcp_server_path: Optional[str] = None,
        llm_provider: Optional[LLMProvider] = None,
        llm_model: Optional[str] = None,
        settings: Optional[Settings] = None
    ):
        """
        Inicializa o agente.
        
        Args:
            mcp_server_path: Caminho para o MCP Server (opcional).
            llm_provider: Provedor de LLM a usar.
            llm_model: Modelo de LLM específico.
            settings: Configurações do agente.
        """
        self._settings = settings or get_settings()
        
        # Configura caminho do MCP Server
        if mcp_server_path:
            self._settings.mcp_server_path = Path(mcp_server_path)
        
        self._llm_provider = llm_provider or self._settings.default_llm_provider
        self._llm_model = llm_model or self._settings.default_llm_model
        
        # Componentes (inicializados sob demanda)
        self._mcp_client: Optional[MCPClient] = None
        self._dependency_graph: Optional[DependencyGraph] = None
        self._impact_analyzer: Optional[ImpactAnalyzer] = None
        self._dax_refactor: Optional[DAXRefactor] = None
        self._validator: Optional[DAXValidator] = None
        
        # Estado
        self._connected = False
        self._model_path: Optional[str] = None
        
        logger.info(
            "RefactorAgent inicializado",
            llm_provider=self._llm_provider.value,
            llm_model=self._llm_model
        )
    
    async def connect(self, model_path: str) -> bool:
        """
        Conecta ao modelo semântico.
        
        Args:
            model_path: Caminho para o arquivo .pbip ou pasta TMDL.
            
        Returns:
            True se conectou com sucesso.
        """
        logger.info("Conectando ao modelo", path=model_path)
        
        # Inicializa cliente MCP
        self._mcp_client = MCPClient(settings=self._settings)
        
        # Tenta iniciar servidor
        started = await self._mcp_client.start()
        if not started:
            logger.warning(
                "Servidor MCP não disponível, continuando em modo offline"
            )
        
        # Conecta ao modelo
        if self._mcp_client.is_connected:
            connected = await self._mcp_client.connect_model(model_path)
            if not connected:
                logger.warning("Falha ao conectar modelo via MCP")
        
        # Inicializa componentes
        self._dependency_graph = DependencyGraph()
        self._impact_analyzer = ImpactAnalyzer(self._dependency_graph)
        self._dax_refactor = DAXRefactor(settings=self._settings)
        self._validator = DAXValidator(
            mcp_client=self._mcp_client,
            settings=self._settings
        )
        
        # Carrega modelo no grafo
        await self._load_model_into_graph()
        
        self._connected = True
        self._model_path = model_path
        
        logger.info(
            "Modelo conectado",
            path=model_path,
            tables=len(self._dependency_graph._tables),
            mcp_available=self._mcp_client.is_connected if self._mcp_client else False
        )
        
        return True
    
    async def disconnect(self) -> None:
        """Desconecta do modelo."""
        if self._mcp_client:
            await self._mcp_client.stop()
            self._mcp_client = None
        
        self._connected = False
        self._model_path = None
        self._dependency_graph = None
        
        logger.info("Desconectado do modelo")
    
    def analyze_impact(
        self,
        change_type: str,
        table: Optional[str] = None,
        old_name: Optional[str] = None,
        new_name: Optional[str] = None,
        object_name: Optional[str] = None
    ) -> ImpactAnalysis:
        """
        Analisa o impacto de uma mudança proposta.
        
        Args:
            change_type: Tipo de mudança (rename_column, rename_table, etc.).
            table: Nome da tabela (para colunas).
            old_name: Nome atual do objeto.
            new_name: Novo nome do objeto.
            object_name: Nome do objeto (alternativo a old_name).
            
        Returns:
            Análise de impacto detalhada.
        """
        if not self._connected:
            raise RuntimeError("Agente não conectado a nenhum modelo")
        
        # Normaliza parâmetros
        obj_name = old_name or object_name
        if not obj_name:
            raise ValueError("Nome do objeto é obrigatório (old_name ou object_name)")
        
        # Cria mudança proposta
        change = ProposedChange(
            change_type=ChangeType(change_type),
            table_name=table,
            object_name=obj_name,
            new_value=new_name
        )
        
        logger.info(
            "Analisando impacto",
            change_type=change_type,
            object_name=obj_name,
            new_name=new_name
        )
        
        return self._impact_analyzer.analyze(change)
    
    async def refactor(
        self,
        impact: ImpactAnalysis,
        validate: bool = True,
        apply: bool = False,
        llm_provider: Optional[LLMProvider] = None,
        llm_model: Optional[str] = None
    ) -> RefactorResult:
        """
        Executa a refatoração baseada na análise de impacto.
        
        Args:
            impact: Análise de impacto da mudança.
            validate: Se deve validar as expressões refatoradas.
            apply: Se deve aplicar as mudanças ao modelo.
            llm_provider: Provedor de LLM (opcional, usa padrão).
            llm_model: Modelo de LLM (opcional, usa padrão).
            
        Returns:
            Resultado da refatoração.
        """
        if not self._connected:
            raise RuntimeError("Agente não conectado a nenhum modelo")
        
        logger.info(
            "Iniciando refatoração",
            change_type=impact.change_type.value,
            total_impacts=impact.total_impacted,
            validate=validate,
            apply=apply
        )
        
        # Executa refatoração com LLM
        result = await self._dax_refactor.refactor(
            impact_analysis=impact,
            llm_provider=llm_provider or self._llm_provider,
            llm_model=llm_model or self._llm_model
        )
        
        # Valida se solicitado
        if validate:
            result = await self._validator.validate_batch(
                result,
                skip_performance=True  # Performance é opcional
            )
        
        # Aplica se solicitado
        if apply and result.status == RefactorStatus.COMPLETED:
            result = await self._apply_changes(result)
        
        logger.info(
            "Refatoração concluída",
            status=result.status.value,
            successful=result.successful_items,
            failed=result.failed_items,
            applied=result.applied
        )
        
        return result
    
    async def refactor_column_rename(
        self,
        table: str,
        old_name: str,
        new_name: str,
        validate: bool = True,
        apply: bool = False
    ) -> RefactorResult:
        """
        Atalho para refatoração de renomeio de coluna.
        
        Args:
            table: Nome da tabela.
            old_name: Nome atual da coluna.
            new_name: Novo nome da coluna.
            validate: Se deve validar.
            apply: Se deve aplicar.
            
        Returns:
            Resultado da refatoração.
        """
        impact = self.analyze_impact(
            change_type="rename_column",
            table=table,
            old_name=old_name,
            new_name=new_name
        )
        
        return await self.refactor(
            impact=impact,
            validate=validate,
            apply=apply
        )
    
    async def dry_run(
        self,
        change_type: str,
        **kwargs
    ) -> RefactorResult:
        """
        Executa uma simulação completa sem aplicar mudanças.
        
        Args:
            change_type: Tipo de mudança.
            **kwargs: Argumentos adicionais para analyze_impact.
            
        Returns:
            Resultado simulado.
        """
        impact = self.analyze_impact(change_type=change_type, **kwargs)
        return await self.refactor(impact=impact, validate=True, apply=False)
    
    def get_model_summary(self) -> dict:
        """
        Retorna um resumo do modelo conectado.
        
        Returns:
            Dicionário com estatísticas do modelo.
        """
        if not self._connected or not self._dependency_graph:
            return {"connected": False}
        
        from pbi_refactor_agent.models import ObjectType
        
        tables = list(self._dependency_graph.iterate_objects(ObjectType.TABLE))
        measures = list(self._dependency_graph.iterate_objects(ObjectType.MEASURE))
        calc_cols = list(self._dependency_graph.iterate_objects(ObjectType.CALCULATED_COLUMN))
        
        return {
            "connected": True,
            "model_path": self._model_path,
            "statistics": {
                "tables": len(tables),
                "measures": len(measures),
                "calculated_columns": len(calc_cols),
                "relationships": len(self._dependency_graph._relationships),
                "total_nodes": self._dependency_graph.node_count,
                "total_edges": self._dependency_graph.edge_count,
            },
            "mcp_connected": self._mcp_client.is_connected if self._mcp_client else False
        }
    
    async def _load_model_into_graph(self) -> None:
        """Carrega o modelo no grafo de dependências."""
        if not self._mcp_client or not self._mcp_client.is_connected:
            logger.debug("MCP não disponível, grafo permanece vazio")
            return
        
        logger.debug("Carregando modelo no grafo de dependências")
        
        try:
            # Carrega tabelas
            tables = await self._mcp_client.list_tables()
            for table in tables:
                self._dependency_graph.add_table(table)
                
                # Carrega colunas da tabela
                columns = await self._mcp_client.list_columns(table.name)
                for column in columns:
                    self._dependency_graph.add_column(column)
            
            # Carrega medidas
            measures = await self._mcp_client.list_measures()
            for measure in measures:
                self._dependency_graph.add_measure(measure)
            
            # Carrega colunas calculadas
            calc_columns = await self._mcp_client.list_calculated_columns()
            for calc_col in calc_columns:
                self._dependency_graph.add_calculated_column(calc_col)
            
            # Carrega relacionamentos
            relationships = await self._mcp_client.list_relationships()
            for rel in relationships:
                self._dependency_graph.add_relationship(rel)
            
            logger.info(
                "Modelo carregado no grafo",
                nodes=self._dependency_graph.node_count,
                edges=self._dependency_graph.edge_count
            )
            
        except Exception as e:
            logger.error("Erro ao carregar modelo", error=str(e))
    
    async def _apply_changes(self, result: RefactorResult) -> RefactorResult:
        """
        Aplica as mudanças ao modelo em uma transação.
        
        Args:
            result: Resultado da refatoração.
            
        Returns:
            Resultado atualizado.
        """
        if not self._mcp_client or not self._mcp_client.is_connected:
            logger.warning("MCP não disponível, mudanças não aplicadas")
            return result
        
        logger.info("Aplicando mudanças ao modelo")
        
        try:
            # Inicia transação
            transaction_id = await self._mcp_client.begin_transaction()
            result.transaction_id = transaction_id
            
            # Aplica cada item validado
            operations = []
            
            for item in result.items:
                if not item.is_validated:
                    continue
                
                obj = item.object
                
                if obj.object_type.value == "measure":
                    operations.append({
                        "type": "update_measure",
                        "name": obj.name,
                        "table": obj.table_name,
                        "expression": item.refactored_expression
                    })
                elif obj.object_type.value == "calculated_column":
                    operations.append({
                        "type": "update_calculated_column",
                        "table": obj.table_name,
                        "name": obj.name,
                        "expression": item.refactored_expression
                    })
            
            # Aplica renomeio do objeto original se for rename
            impact = result.impact_analysis
            if impact.change_type == ChangeType.RENAME_COLUMN:
                operations.insert(0, {
                    "type": "rename_column",
                    "table": impact.target_object.table_name,
                    "old_name": impact.target_object.name,
                    "new_name": impact.new_value
                })
            
            # Executa em batch
            if operations:
                batch_result = await self._mcp_client.batch_update(operations)
                
                if batch_result.get("success"):
                    # Commit
                    await self._mcp_client.commit_transaction(transaction_id)
                    result.applied = True
                    
                    # Marca itens como aplicados
                    for item in result.items:
                        if item.is_validated:
                            item.applied = True
                    
                    logger.info(
                        "Mudanças aplicadas com sucesso",
                        operations=len(operations)
                    )
                else:
                    # Rollback
                    await self._mcp_client.rollback_transaction(transaction_id)
                    result.rolled_back = True
                    result.error_message = batch_result.get("error", "Falha ao aplicar mudanças")
                    
                    logger.error(
                        "Falha ao aplicar mudanças, rollback executado",
                        error=result.error_message
                    )
            
        except Exception as e:
            logger.error("Erro ao aplicar mudanças", error=str(e))
            result.error_message = str(e)
            
            # Tenta rollback
            if result.transaction_id:
                try:
                    await self._mcp_client.rollback_transaction(result.transaction_id)
                    result.rolled_back = True
                except Exception:
                    pass
        
        return result
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.disconnect()
