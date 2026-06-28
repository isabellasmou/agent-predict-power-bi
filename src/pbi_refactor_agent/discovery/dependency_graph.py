"""
Grafo de Dependências do Modelo Semântico.

Implementa um grafo dirigido para representar as dependências
entre objetos do modelo Power BI (medidas, colunas calculadas,
relacionamentos, etc.).
"""

import re
from typing import Any, Iterator, Optional

import networkx as nx
import structlog

from pbi_refactor_agent.models import (
    CalculatedColumnInfo,
    ColumnInfo,
    Dependency,
    MeasureInfo,
    ObjectType,
    RelationshipInfo,
    SemanticObject,
    TableInfo,
)

logger = structlog.get_logger(__name__)


class DependencyGraph:
    """
    Grafo de dependências do modelo semântico.
    
    Utiliza NetworkX para representar as dependências entre objetos,
    permitindo análise de impacto em cascata.
    """
    
    def __init__(self):
        """Inicializa o grafo de dependências."""
        self._graph = nx.DiGraph()
        self._objects: dict[str, SemanticObject] = {}
        self._tables: dict[str, TableInfo] = {}
        self._relationships: list[RelationshipInfo] = []
        
        # Regex para extrair referências em expressões DAX
        self._column_ref_pattern = re.compile(
            r"'?([^'\[\]]+)'?\[([^\]]+)\]"
        )
        self._measure_ref_pattern = re.compile(
            r"\[([^\]]+)\]"
        )
    
    @property
    def node_count(self) -> int:
        """Retorna o número de nós no grafo."""
        return self._graph.number_of_nodes()
    
    @property
    def edge_count(self) -> int:
        """Retorna o número de arestas no grafo."""
        return self._graph.number_of_edges()
    
    def clear(self) -> None:
        """Limpa o grafo."""
        self._graph.clear()
        self._objects.clear()
        self._tables.clear()
        self._relationships.clear()
    
    def add_table(self, table: TableInfo) -> None:
        """
        Adiciona uma tabela ao grafo.
        
        Args:
            table: Informações da tabela.
        """
        node_id = self._get_node_id(table)
        self._graph.add_node(node_id, **table.model_dump())
        self._objects[node_id] = table
        self._tables[table.name] = table
        
        logger.debug("Tabela adicionada ao grafo", table=table.name)
    
    def add_column(self, column: ColumnInfo) -> None:
        """
        Adiciona uma coluna ao grafo.
        
        Args:
            column: Informações da coluna.
        """
        node_id = self._get_node_id(column)
        self._graph.add_node(node_id, **column.model_dump())
        self._objects[node_id] = column
        
        # Adiciona edge da tabela para a coluna
        if column.table_name:
            table_id = f"table:{column.table_name}"
            if table_id in self._graph:
                self._graph.add_edge(table_id, node_id, relation="contains")
        
        logger.debug("Coluna adicionada ao grafo", column=column.full_name)
    
    def add_measure(self, measure: MeasureInfo) -> None:
        """
        Adiciona uma medida ao grafo e analisa suas dependências.
        
        Args:
            measure: Informações da medida.
        """
        node_id = self._get_node_id(measure)
        self._graph.add_node(node_id, **measure.model_dump())
        self._objects[node_id] = measure
        
        # Analisa dependências na expressão DAX
        if measure.expression:
            self._analyze_expression_dependencies(node_id, measure.expression)
        
        logger.debug("Medida adicionada ao grafo", measure=measure.name)
    
    def add_calculated_column(self, calc_column: CalculatedColumnInfo) -> None:
        """
        Adiciona uma coluna calculada ao grafo e analisa suas dependências.
        
        Args:
            calc_column: Informações da coluna calculada.
        """
        node_id = self._get_node_id(calc_column)
        self._graph.add_node(node_id, **calc_column.model_dump())
        self._objects[node_id] = calc_column
        
        # Analisa dependências na expressão DAX
        if calc_column.expression:
            self._analyze_expression_dependencies(node_id, calc_column.expression)
        
        logger.debug(
            "Coluna calculada adicionada ao grafo",
            column=calc_column.full_name
        )
    
    def add_relationship(self, relationship: RelationshipInfo) -> None:
        """
        Adiciona um relacionamento ao grafo.
        
        Args:
            relationship: Informações do relacionamento.
        """
        self._relationships.append(relationship)
        
        # Adiciona edges entre as colunas relacionadas
        from_id = f"column:{relationship.from_table}.{relationship.from_column}"
        to_id = f"column:{relationship.to_table}.{relationship.to_column}"
        
        if from_id in self._graph and to_id in self._graph:
            self._graph.add_edge(
                from_id,
                to_id,
                relation="relationship",
                relationship_name=relationship.name
            )
        
        logger.debug(
            "Relacionamento adicionado ao grafo",
            relationship=relationship.full_name
        )
    
    def get_object(self, node_id: str) -> Optional[SemanticObject]:
        """
        Retorna um objeto pelo seu ID.
        
        Args:
            node_id: ID do nó.
            
        Returns:
            Objeto semântico ou None se não encontrado.
        """
        return self._objects.get(node_id)
    
    def get_direct_dependents(self, node_id: str) -> list[SemanticObject]:
        """
        Retorna os objetos que dependem diretamente do nó especificado.
        
        Args:
            node_id: ID do nó.
            
        Returns:
            Lista de objetos dependentes.
        """
        dependents = []
        
        if node_id not in self._graph:
            return dependents
        
        # Encontra predecessores (objetos que apontam para este nó)
        for pred_id in self._graph.predecessors(node_id):
            if pred_id in self._objects:
                dependents.append(self._objects[pred_id])
        
        return dependents
    
    def get_all_dependents(
        self,
        node_id: str,
        max_depth: Optional[int] = None
    ) -> list[Dependency]:
        """
        Retorna todos os objetos que dependem do nó, incluindo indiretos.
        
        Args:
            node_id: ID do nó.
            max_depth: Profundidade máxima de busca (None = sem limite).
            
        Returns:
            Lista de dependências com informação de profundidade.
        """
        dependencies = []
        visited = set()
        
        def _traverse(current_id: str, depth: int):
            if current_id in visited:
                return
            if max_depth is not None and depth > max_depth:
                return
            
            visited.add(current_id)
            
            for pred_id in self._graph.predecessors(current_id):
                if pred_id in self._objects and pred_id != node_id:
                    source_obj = self._objects.get(node_id)
                    target_obj = self._objects[pred_id]
                    
                    if source_obj:
                        dep = Dependency(
                            source=source_obj,
                            target=target_obj,
                            dependency_type="direct" if depth == 1 else "indirect",
                            depth=depth
                        )
                        dependencies.append(dep)
                    
                    _traverse(pred_id, depth + 1)
        
        _traverse(node_id, 1)
        return dependencies
    
    def get_dependencies_of(self, node_id: str) -> list[SemanticObject]:
        """
        Retorna os objetos dos quais o nó depende.
        
        Args:
            node_id: ID do nó.
            
        Returns:
            Lista de dependências.
        """
        deps = []
        
        if node_id not in self._graph:
            return deps
        
        for succ_id in self._graph.successors(node_id):
            if succ_id in self._objects:
                deps.append(self._objects[succ_id])
        
        return deps
    
    def find_by_name(
        self,
        name: str,
        table_name: Optional[str] = None,
        object_type: Optional[ObjectType] = None
    ) -> Optional[SemanticObject]:
        """
        Encontra um objeto pelo nome.
        
        Args:
            name: Nome do objeto.
            table_name: Nome da tabela (opcional).
            object_type: Tipo do objeto (opcional).
            
        Returns:
            Objeto encontrado ou None.
        """
        for node_id, obj in self._objects.items():
            if obj.name.lower() == name.lower():
                if table_name and obj.table_name:
                    if obj.table_name.lower() != table_name.lower():
                        continue
                if object_type and obj.object_type != object_type:
                    continue
                return obj
        
        return None
    
    def find_objects_referencing(
        self,
        table_name: str,
        column_name: str
    ) -> list[SemanticObject]:
        """
        Encontra todos os objetos que referenciam uma coluna específica.
        
        Args:
            table_name: Nome da tabela.
            column_name: Nome da coluna.
            
        Returns:
            Lista de objetos que referenciam a coluna.
        """
        results = []
        
        # Padrões de referência a buscar
        patterns = [
            f"'{table_name}'[{column_name}]",
            f"{table_name}[{column_name}]",
            f"[{column_name}]",  # Pode ser ambíguo, mas incluímos
        ]
        
        for node_id, obj in self._objects.items():
            if obj.expression:
                for pattern in patterns:
                    if pattern.lower() in obj.expression.lower():
                        results.append(obj)
                        break
        
        return results
    
    def get_relationships_for_column(
        self,
        table_name: str,
        column_name: str
    ) -> list[RelationshipInfo]:
        """
        Retorna relacionamentos que envolvem uma coluna específica.
        
        Args:
            table_name: Nome da tabela.
            column_name: Nome da coluna.
            
        Returns:
            Lista de relacionamentos.
        """
        results = []
        
        for rel in self._relationships:
            if (
                (rel.from_table == table_name and rel.from_column == column_name)
                or (rel.to_table == table_name and rel.to_column == column_name)
            ):
                results.append(rel)
        
        return results
    
    def iterate_objects(
        self,
        object_type: Optional[ObjectType] = None
    ) -> Iterator[SemanticObject]:
        """
        Itera sobre todos os objetos do grafo.
        
        Args:
            object_type: Filtrar por tipo de objeto.
            
        Yields:
            Objetos do grafo.
        """
        for obj in self._objects.values():
            if object_type is None or obj.object_type == object_type:
                yield obj
    
    def to_dict(self) -> dict[str, Any]:
        """
        Converte o grafo para dicionário.
        
        Returns:
            Representação em dicionário.
        """
        return {
            "nodes": [obj.model_dump() for obj in self._objects.values()],
            "edges": list(self._graph.edges(data=True)),
            "relationships": [rel.model_dump() for rel in self._relationships],
            "stats": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "table_count": len(self._tables),
                "relationship_count": len(self._relationships),
            }
        }
    
    def _get_node_id(self, obj: SemanticObject) -> str:
        """
        Gera um ID único para um objeto.
        
        Args:
            obj: Objeto semântico.
            
        Returns:
            ID único do nó.
        """
        prefix = obj.object_type.value
        
        if obj.table_name:
            return f"{prefix}:{obj.table_name}.{obj.name}"
        return f"{prefix}:{obj.name}"
    
    def _analyze_expression_dependencies(
        self,
        node_id: str,
        expression: str
    ) -> None:
        """
        Analisa uma expressão DAX e adiciona as dependências ao grafo.
        
        Args:
            node_id: ID do nó que contém a expressão.
            expression: Expressão DAX a analisar.
        """
        # Encontra referências a colunas: 'Tabela'[Coluna] ou Tabela[Coluna]
        for match in self._column_ref_pattern.finditer(expression):
            table_name = match.group(1).strip("'")
            column_name = match.group(2)
            
            # Procura a coluna no grafo
            target_id = f"column:{table_name}.{column_name}"
            if target_id not in self._graph:
                target_id = f"calculated_column:{table_name}.{column_name}"
            
            if target_id in self._graph:
                self._graph.add_edge(node_id, target_id, relation="references")
        
        # Encontra referências a medidas: [Medida]
        # Precisa filtrar as que já foram capturadas como colunas
        expression_no_columns = self._column_ref_pattern.sub("", expression)
        
        for match in self._measure_ref_pattern.finditer(expression_no_columns):
            measure_name = match.group(1)
            
            # Procura a medida no grafo
            target_id = f"measure:{measure_name}"
            if target_id in self._graph:
                self._graph.add_edge(node_id, target_id, relation="references")
