"""
Cliente MCP (Model Context Protocol) para Power BI Modeling Server.

Implementa a comunicação com o Power BI Modeling MCP Server
via protocolo stdio para operações no modelo semântico.
"""

import asyncio
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog

from pbi_refactor_agent.config import Settings, get_settings
from pbi_refactor_agent.models import (
    CalculatedColumnInfo,
    ColumnInfo,
    MeasureInfo,
    ObjectType,
    RelationshipInfo,
    TableInfo,
)

logger = structlog.get_logger(__name__)


class MCPClient:
    """
    Cliente para comunicação com o Power BI Modeling MCP Server.
    
    Utiliza o protocolo MCP (Model Context Protocol) via stdio
    para operações no modelo semântico Power BI.
    """
    
    def __init__(
        self,
        server_path: Optional[Path] = None,
        settings: Optional[Settings] = None,
        timeout: int = 30
    ):
        """
        Inicializa o cliente MCP.
        
        Args:
            server_path: Caminho para o executável do MCP Server.
            settings: Configurações do agente.
            timeout: Timeout padrão para operações.
        """
        self._settings = settings or get_settings()
        self._server_path = server_path or self._settings.mcp_server_path
        self._timeout = timeout or self._settings.mcp_server_timeout
        
        self._process: Optional[subprocess.Popen] = None
        self._connected = False
        self._model_path: Optional[str] = None
        self._request_id = 0
        
        logger.info(
            "MCPClient inicializado",
            server_path=str(self._server_path) if self._server_path else "não configurado"
        )
    
    @property
    def is_connected(self) -> bool:
        """Retorna se está conectado ao servidor."""
        return self._connected and self._process is not None
    
    async def start(self) -> bool:
        """
        Inicia o servidor MCP.
        
        Returns:
            True se iniciou com sucesso.
        """
        if not self._server_path:
            logger.warning("Caminho do servidor MCP não configurado")
            return False
        
        if not self._server_path.exists():
            logger.error(
                "Servidor MCP não encontrado",
                path=str(self._server_path)
            )
            return False
        
        logger.info("Iniciando servidor MCP")
        
        try:
            self._process = subprocess.Popen(
                [str(self._server_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Aguarda inicialização
            await asyncio.sleep(1)
            
            if self._process.poll() is not None:
                stderr = self._process.stderr.read()
                logger.error(
                    "Servidor MCP falhou ao iniciar",
                    stderr=stderr
                )
                return False
            
            self._connected = True
            logger.info("Servidor MCP iniciado com sucesso")
            return True
            
        except Exception as e:
            logger.error("Erro ao iniciar servidor MCP", error=str(e))
            return False
    
    async def stop(self) -> None:
        """Para o servidor MCP."""
        if self._process:
            logger.info("Parando servidor MCP")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            
            self._process = None
            self._connected = False
            logger.info("Servidor MCP parado")
    
    async def connect_model(self, model_path: str) -> bool:
        """
        Conecta a um modelo semântico.
        
        Args:
            model_path: Caminho para o arquivo .pbip ou pasta TMDL.
            
        Returns:
            True se conectou com sucesso.
        """
        logger.info("Conectando ao modelo", path=model_path)
        
        result = await self._call_tool(
            "connect",
            {"path": model_path}
        )
        
        if result.get("success"):
            self._model_path = model_path
            logger.info("Modelo conectado com sucesso")
            return True
        
        logger.error(
            "Falha ao conectar modelo",
            error=result.get("error")
        )
        return False
    
    async def get_model_info(self) -> dict[str, Any]:
        """
        Obtém informações do modelo conectado.
        
        Returns:
            Dicionário com informações do modelo.
        """
        return await self._call_tool("get_model_info", {})
    
    async def list_tables(self) -> list[TableInfo]:
        """
        Lista todas as tabelas do modelo.
        
        Returns:
            Lista de informações de tabelas.
        """
        result = await self._call_tool("list_tables", {})
        
        tables = []
        for table_data in result.get("tables", []):
            table = TableInfo(
                name=table_data["name"],
                columns=table_data.get("columns", []),
                measures=table_data.get("measures", []),
                calculated_columns=table_data.get("calculated_columns", []),
                row_count=table_data.get("row_count"),
                description=table_data.get("description")
            )
            tables.append(table)
        
        return tables
    
    async def list_columns(self, table_name: str) -> list[ColumnInfo]:
        """
        Lista todas as colunas de uma tabela.
        
        Args:
            table_name: Nome da tabela.
            
        Returns:
            Lista de informações de colunas.
        """
        result = await self._call_tool(
            "list_columns",
            {"table": table_name}
        )
        
        columns = []
        for col_data in result.get("columns", []):
            column = ColumnInfo(
                name=col_data["name"],
                table_name=table_name,
                data_type=col_data.get("data_type", "string"),
                is_nullable=col_data.get("is_nullable", True),
                is_key=col_data.get("is_key", False),
                description=col_data.get("description")
            )
            columns.append(column)
        
        return columns
    
    async def list_measures(self, table_name: Optional[str] = None) -> list[MeasureInfo]:
        """
        Lista medidas do modelo.
        
        Args:
            table_name: Nome da tabela (opcional, lista todas se None).
            
        Returns:
            Lista de informações de medidas.
        """
        params = {}
        if table_name:
            params["table"] = table_name
        
        result = await self._call_tool("list_measures", params)
        
        measures = []
        for measure_data in result.get("measures", []):
            measure = MeasureInfo(
                name=measure_data["name"],
                table_name=measure_data.get("table"),
                expression=measure_data.get("expression"),
                format_string=measure_data.get("format_string"),
                display_folder=measure_data.get("display_folder"),
                description=measure_data.get("description")
            )
            measures.append(measure)
        
        return measures
    
    async def list_calculated_columns(
        self,
        table_name: Optional[str] = None
    ) -> list[CalculatedColumnInfo]:
        """
        Lista colunas calculadas do modelo.
        
        Args:
            table_name: Nome da tabela (opcional).
            
        Returns:
            Lista de informações de colunas calculadas.
        """
        params = {}
        if table_name:
            params["table"] = table_name
        
        result = await self._call_tool("list_calculated_columns", params)
        
        calc_columns = []
        for col_data in result.get("calculated_columns", []):
            col = CalculatedColumnInfo(
                name=col_data["name"],
                table_name=col_data.get("table"),
                expression=col_data.get("expression"),
                data_type=col_data.get("data_type", "string"),
                description=col_data.get("description")
            )
            calc_columns.append(col)
        
        return calc_columns
    
    async def list_relationships(self) -> list[RelationshipInfo]:
        """
        Lista todos os relacionamentos do modelo.
        
        Returns:
            Lista de informações de relacionamentos.
        """
        result = await self._call_tool("list_relationships", {})
        
        relationships = []
        for rel_data in result.get("relationships", []):
            rel = RelationshipInfo(
                name=rel_data.get("name", ""),
                from_table=rel_data["from_table"],
                from_column=rel_data["from_column"],
                to_table=rel_data["to_table"],
                to_column=rel_data["to_column"],
                is_active=rel_data.get("is_active", True),
                cross_filter_direction=rel_data.get("cross_filter_direction", "Single")
            )
            relationships.append(rel)
        
        return relationships
    
    async def get_dependencies(
        self,
        object_name: str,
        table_name: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Obtém dependências de um objeto.
        
        Args:
            object_name: Nome do objeto.
            table_name: Nome da tabela (para colunas).
            
        Returns:
            Dicionário com dependências.
        """
        params = {"name": object_name}
        if table_name:
            params["table"] = table_name
        
        return await self._call_tool("get_dependencies", params)
    
    async def execute_dax(
        self,
        query: str,
        timeout: Optional[int] = None,
        capture_timing: bool = False
    ) -> dict[str, Any]:
        """
        Executa uma query DAX.
        
        Args:
            query: Query DAX a executar.
            timeout: Timeout em segundos.
            capture_timing: Se deve capturar tempo de execução.
            
        Returns:
            Resultado da query.
        """
        params = {
            "query": query,
            "capture_timing": capture_timing
        }
        
        if timeout:
            params["timeout"] = timeout
        
        return await self._call_tool("execute_dax", params)
    
    async def validate_expression(self, expression: str) -> dict[str, Any]:
        """
        Valida uma expressão DAX sem executá-la.
        
        Args:
            expression: Expressão DAX a validar.
            
        Returns:
            Resultado da validação.
        """
        return await self._call_tool(
            "validate_expression",
            {"expression": expression}
        )
    
    async def rename_column(
        self,
        table_name: str,
        old_name: str,
        new_name: str
    ) -> dict[str, Any]:
        """
        Renomeia uma coluna.
        
        Args:
            table_name: Nome da tabela.
            old_name: Nome atual da coluna.
            new_name: Novo nome da coluna.
            
        Returns:
            Resultado da operação.
        """
        return await self._call_tool(
            "rename_column",
            {
                "table": table_name,
                "old_name": old_name,
                "new_name": new_name
            }
        )
    
    async def update_measure(
        self,
        name: str,
        expression: str,
        table_name: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Atualiza uma medida.
        
        Args:
            name: Nome da medida.
            expression: Nova expressão DAX.
            table_name: Nome da tabela (opcional).
            
        Returns:
            Resultado da operação.
        """
        params = {
            "name": name,
            "expression": expression
        }
        if table_name:
            params["table"] = table_name
        
        return await self._call_tool("update_measure", params)
    
    async def update_calculated_column(
        self,
        table_name: str,
        name: str,
        expression: str
    ) -> dict[str, Any]:
        """
        Atualiza uma coluna calculada.
        
        Args:
            table_name: Nome da tabela.
            name: Nome da coluna calculada.
            expression: Nova expressão DAX.
            
        Returns:
            Resultado da operação.
        """
        return await self._call_tool(
            "update_calculated_column",
            {
                "table": table_name,
                "name": name,
                "expression": expression
            }
        )
    
    async def begin_transaction(self) -> str:
        """
        Inicia uma transação.
        
        Returns:
            ID da transação.
        """
        result = await self._call_tool("begin_transaction", {})
        return result.get("transaction_id", str(uuid.uuid4()))
    
    async def commit_transaction(self, transaction_id: str) -> bool:
        """
        Confirma uma transação.
        
        Args:
            transaction_id: ID da transação.
            
        Returns:
            True se confirmou com sucesso.
        """
        result = await self._call_tool(
            "commit_transaction",
            {"transaction_id": transaction_id}
        )
        return result.get("success", False)
    
    async def rollback_transaction(self, transaction_id: str) -> bool:
        """
        Reverte uma transação.
        
        Args:
            transaction_id: ID da transação.
            
        Returns:
            True se reverteu com sucesso.
        """
        result = await self._call_tool(
            "rollback_transaction",
            {"transaction_id": transaction_id}
        )
        return result.get("success", False)
    
    async def batch_update(
        self,
        operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Executa múltiplas operações em lote.
        
        Args:
            operations: Lista de operações a executar.
            
        Returns:
            Resultado do lote.
        """
        return await self._call_tool(
            "batch_update",
            {"operations": operations}
        )
    
    async def validate_model_integrity(self) -> dict[str, Any]:
        """
        Valida a integridade do modelo.
        
        Returns:
            Resultado da validação.
        """
        return await self._call_tool("validate_model_integrity", {})
    
    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Chama uma ferramenta do MCP Server.
        
        Args:
            tool_name: Nome da ferramenta.
            arguments: Argumentos da ferramenta.
            
        Returns:
            Resultado da chamada.
        """
        if not self.is_connected:
            logger.warning(
                "Cliente não conectado, retornando resultado simulado",
                tool_name=tool_name
            )
            return self._simulate_response(tool_name, arguments)
        
        self._request_id += 1
        
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        logger.debug(
            "Chamando ferramenta MCP",
            tool_name=tool_name,
            request_id=self._request_id
        )
        
        try:
            # Envia requisição
            request_str = json.dumps(request) + "\n"
            self._process.stdin.write(request_str)
            self._process.stdin.flush()
            
            # Aguarda resposta
            response_str = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    self._process.stdout.readline
                ),
                timeout=self._timeout
            )
            
            response = json.loads(response_str)
            
            if "error" in response:
                logger.error(
                    "Erro na chamada MCP",
                    tool_name=tool_name,
                    error=response["error"]
                )
                return {"success": False, "error": response["error"]}
            
            return response.get("result", {})
            
        except asyncio.TimeoutError:
            logger.error(
                "Timeout na chamada MCP",
                tool_name=tool_name,
                timeout=self._timeout
            )
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            logger.error(
                "Erro na chamada MCP",
                tool_name=tool_name,
                error=str(e)
            )
            return {"success": False, "error": str(e)}
    
    def _simulate_response(
        self,
        tool_name: str,
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Simula resposta quando não conectado (para testes).
        
        Args:
            tool_name: Nome da ferramenta.
            arguments: Argumentos da ferramenta.
            
        Returns:
            Resposta simulada.
        """
        # Respostas simuladas para desenvolvimento/testes
        simulated = {
            "get_model_info": {
                "name": "Simulated Model",
                "tables": 0,
                "measures": 0,
                "relationships": 0
            },
            "list_tables": {"tables": []},
            "list_measures": {"measures": []},
            "list_columns": {"columns": []},
            "list_calculated_columns": {"calculated_columns": []},
            "list_relationships": {"relationships": []},
            "get_dependencies": {"dependencies": []},
            "validate_expression": {"is_valid": True},
            "execute_dax": {"result": None},
            "begin_transaction": {"transaction_id": str(uuid.uuid4())},
            "commit_transaction": {"success": True},
            "rollback_transaction": {"success": True},
        }
        
        return simulated.get(tool_name, {"success": True})
    
    async def __aenter__(self):
        """Context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.stop()
