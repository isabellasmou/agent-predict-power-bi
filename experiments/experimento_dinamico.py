#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experimento Dinâmico - PBI Refactor Agent
TCC - Isabella da Silva Moura | FAETERJ 2026

Gera casos de teste AUTOMATICAMENTE a partir do modelo .pbit real carregado.
Identifica medidas importantes e simula renomeações de colunas/tabelas/medidas
que realmente existem no modelo do usuário.

Diferença do experimento_controlado.py:
- experimento_controlado.py: casos fictícios hardcoded para benchmark de LLMs
- experimento_dinamico.py: casos REAIS gerados do modelo carregado (ESTE ARQUIVO)
"""

import asyncio
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog

from pbi_refactor_agent.models import (
    ChangeType,
    ImpactAnalysis,
    ImpactedObject,
    ObjectType,
    SemanticObject,
)
from pbi_refactor_agent.discovery import DependencyGraph, ImpactAnalyzer
from pbi_refactor_agent.refactor import DAXRefactor
from pbi_refactor_agent.config import LLMProvider, Settings
from pbi_refactor_agent.utils.pbix_extractor import ModelMetadata

logger = structlog.get_logger(__name__)


class ExperimentoDinamico:
    """
    Gera e executa experimento controlado usando o modelo REAL carregado.
    """
    
    def __init__(
        self,
        metadata: ModelMetadata,
        graph: DependencyGraph,
        dax_refactor: DAXRefactor,
    ):
        self.metadata = metadata
        self.graph = graph
        self.dax_refactor = dax_refactor
        self.impact_analyzer = ImpactAnalyzer(graph)
    
    def gerar_casos_de_teste(self, max_casos: int = 15) -> List[Dict[str, Any]]:
        """
        Gera casos de teste dinâmicos baseados no modelo real.
        
        Estratégia:
        1. Identifica as 10 medidas mais complexas (mais dependências)
        2. Para cada medida, extrai colunas referenciadas
        3. Gera caso de teste: "renomear coluna X para X_New"
        4. Limita a max_casos casos
        
        Returns:
            Lista de casos de teste com estrutura compatível com experimento_controlado
        """
        logger.info("gerando_casos_dinamicos", max_casos=max_casos)
        casos = []
        caso_id = 1
        
        # Coletar todas as medidas do modelo
        todas_medidas = []
        for table in self.metadata.business_tables:
            for measure in table.measures:
                if not measure.is_hidden and measure.expression:
                    todas_medidas.append({
                        "table": table.name,
                        "measure": measure,
                        "complexity_score": self._calcular_score_complexidade(measure.expression),
                    })
        
        # Ordenar por complexidade (mais complexas primeiro)
        todas_medidas.sort(key=lambda x: x["complexity_score"], reverse=True)
        
        logger.info("medidas_encontradas", total=len(todas_medidas))
        print(f"📊 {len(todas_medidas)} medidas encontradas no modelo")
        
        # Para cada medida, tentar gerar casos de teste
        medidas_processadas = 0
        colunas_encontradas = 0
        
        for item in todas_medidas[:20]:  # Analisa top 20 medidas
            if len(casos) >= max_casos:
                break
            
            medidas_processadas += 1
            table_name = item["table"]
            measure = item["measure"]
            expression = measure.expression
            
            # Debug: mostrar medida sendo processada
            print(f"  Analisando: {table_name}[{measure.name}] (score: {item['complexity_score']})")
            
            # Extrair colunas referenciadas na expressão
            colunas_refs = self._extrair_referencias_colunas(expression, table_name)
            
            if colunas_refs:
                colunas_encontradas += len(colunas_refs)
                print(f"    ✓ {len(colunas_refs)} coluna(s) referenciada(s): {', '.join([f'{c["table"]}[{c["column"]}]' for c in colunas_refs])}")
            else:
                print(f"    ✗ Nenhuma coluna referenciada identificada")
            
            # Para cada coluna referenciada, gerar caso de renomeação
            for col_ref in colunas_refs:
                if len(casos) >= max_casos:
                    break
                
                # Gerar novo nome para a coluna
                new_name = self._gerar_novo_nome_coluna(col_ref["column"])
                
                # Calcular gabarito (expressão esperada após renomeação)
                gabarito = self._calcular_gabarito(
                    expression, 
                    col_ref["table"], 
                    col_ref["column"], 
                    new_name
                )
                
                # Criar caso de teste
                caso = {
                    "id": f"D{caso_id:02d}",
                    "cenario": "Renomeio de Coluna",
                    "descricao": f"Renomear {col_ref['table']}[{col_ref['column']}] → [{new_name}] (afeta {measure.name})",
                    "objetivo_teste": "Validar se o agente atualiza corretamente todas as referências DAX impactadas por uma renomeação simulada.",
                    "change_type": ChangeType.RENAME_COLUMN,
                    "table": col_ref["table"],
                    "old_name": col_ref["column"],
                    "new_name": new_name,
                    "objeto_nome": measure.name,
                    "objeto_tipo": ObjectType.MEASURE,
                    "objeto_tabela": table_name,
                    "expressao_original": expression,
                    "gabarito": gabarito,
                    "medida_original": {
                        "name": measure.name,
                        "table": table_name,
                        "complexity": measure.complexity,
                    }
                }
                
                casos.append(caso)
                caso_id += 1
                
                logger.debug("caso_gerado", 
                    id=caso["id"], 
                    medida=measure.name,
                    coluna=f"{col_ref['table']}[{col_ref['column']}]"
                )
        
        print(f"\n📝 Resumo:")
        print(f"  - Medidas processadas: {medidas_processadas}")
        print(f"  - Colunas encontradas: {colunas_encontradas}")
        print(f"  - Casos de teste gerados: {len(casos)}")
        
        logger.info("casos_gerados", total=len(casos))
        return casos
    
    def _calcular_score_complexidade(self, expression: str) -> int:
        """
        Calcula score de complexidade de uma expressão DAX.
        Quanto maior, mais interessante para testar.
        """
        score = 0
        
        # Funções DAX complexas
        funcoes_complexas = [
            "CALCULATE", "FILTER", "ALL", "SUMX", "AVERAGEX",
            "MAXX", "MINX", "COUNTX", "SUMMARIZE", "ADDCOLUMNS",
            "TOPN", "RANKX", "EARLIER", "RELATED", "RELATEDTABLE"
        ]
        
        for func in funcoes_complexas:
            score += expression.upper().count(func) * 2
        
        # Referências a colunas
        score += len(re.findall(r'\w+\[\w+\]', expression))
        
        # Linhas de código
        score += len(expression.split('\n'))
        
        return score
    
    def _extrair_referencias_colunas(
        self, 
        expression: str, 
        default_table: str
    ) -> List[Dict[str, str]]:
        """
        Extrai todas as referências a colunas na expressão DAX.
        
        Padrões reconhecidos:
        - Tabela[Coluna]
        - [Coluna] (usa default_table)
        """
        refs = []
        
        # Padrão: Tabela[Coluna] ou 'Tabela'[Coluna]
        # Suporta nomes com espaços entre aspas simples
        pattern1 = r"(?:'([^']+)'|(\w+))\[([^\]]+)\]"
        matches = re.finditer(pattern1, expression)
        
        for match in matches:
            # match.group(1) = tabela entre aspas, match.group(2) = tabela sem aspas
            table = match.group(1) if match.group(1) else match.group(2)
            column = match.group(3)
            
            # Verificar se a coluna existe no modelo antes de adicionar
            if self._coluna_existe(table, column):
                refs.append({"table": table, "column": column})
        
        # Remover duplicatas
        refs_unique = []
        seen = set()
        for ref in refs:
            key = f"{ref['table']}.{ref['column']}"
            if key not in seen:
                refs_unique.append(ref)
                seen.add(key)
        
        return refs_unique
    
    def _coluna_existe(self, table_name: str, column_name: str) -> bool:
        """
        Verifica se a coluna existe no modelo.
        DAX é case-insensitive, então fazemos comparação ignorando case.
        """
        table_name_lower = table_name.lower()
        column_name_lower = column_name.lower()
        
        for table in self.metadata.business_tables:
            if table.name.lower() == table_name_lower:
                # Verificar colunas
                for col in table.columns:
                    if col.name.lower() == column_name_lower:
                        return True
                # Verificar colunas calculadas (também são colunas)
                for col in table.columns:
                    if col.name.lower() == column_name_lower:
                        return True
        
        # Verificar em todas as tabelas (incluindo system tables)
        for table in self.metadata.tables:
            if table.name.lower() == table_name_lower:
                for col in table.columns:
                    if col.name.lower() == column_name_lower:
                        return True
        
        return False
    
    def _gerar_novo_nome_coluna(self, nome_original: str) -> str:
        """
        Gera um novo nome para a coluna (simulação de renomeação).
        
        Estratégias:
        - Se termina com "ID", adiciona "New" no início
        - Se tem underscore, substitui por CamelCase
        - Caso contrário, adiciona sufixo "Updated"
        """
        if nome_original.endswith("ID"):
            return f"New{nome_original}"
        elif nome_original.endswith("Date"):
            return f"{nome_original}Time"
        elif "_" in nome_original:
            # snake_case → CamelCase
            parts = nome_original.split("_")
            return "".join(p.capitalize() for p in parts)
        else:
            return f"{nome_original}Updated"
    
    def _calcular_gabarito(
        self, 
        expression: str, 
        table_name: str, 
        old_column: str, 
        new_column: str
    ) -> str:
        """
        Calcula a expressão esperada após renomeação da coluna.
        
        Substitui todas as ocorrências de Tabela[ColunaAntiga] por Tabela[ColunaNova].
        """
        # Padrão exato: table_name[old_column]
        pattern = rf'\b{re.escape(table_name)}\[{re.escape(old_column)}\]'
        replacement = f"{table_name}[{new_column}]"
        
        gabarito = re.sub(pattern, replacement, expression)
        return gabarito
    
    async def executar_experimento(
        self,
        casos: List[Dict[str, Any]],
        llm_provider: LLMProvider,
        llm_model: str,
    ) -> List[Dict[str, Any]]:
        """
        Executa o experimento com os casos de teste gerados.
        
        Returns:
            Lista de resultados com acurácia, tempo, etc.
        """
        logger.info("iniciando_experimento_dinamico", 
            casos=len(casos), 
            provider=llm_provider.value
        )
        
        resultados = []
        
        for i, caso in enumerate(casos, 1):
            logger.info("executando_caso", 
                progresso=f"{i}/{len(casos)}", 
                caso_id=caso["id"]
            )
            
            # Construir ImpactAnalysis
            impact = self._build_impact_analysis(caso)
            
            # Executar refatoração
            inicio = datetime.now()
            try:
                result = await self.dax_refactor.refactor(
                    impact_analysis=impact,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
                tempo = (datetime.now() - inicio).total_seconds()
                
                # Extrair expressão gerada
                if result.items and result.items[0].refactored_expression:
                    expressao_gerada = result.items[0].refactored_expression
                    erro = False
                else:
                    expressao_gerada = ""
                    erro = True
                
            except Exception as e:
                logger.error("erro_refatoracao", caso=caso["id"], erro=str(e))
                expressao_gerada = ""
                tempo = 0.0
                erro = True
            
            # Calcular acurácia
            acuracia_exata = self._calcular_acuracia_exata(
                caso["gabarito"], 
                expressao_gerada
            )
            acuracia_parcial = self._calcular_acuracia_parcial(
                caso["gabarito"], 
                expressao_gerada
            )
            
            # Registrar resultado
            resultado = {
                "caso_id": caso["id"],
                "cenario": caso["cenario"],
                "descricao": caso["descricao"],
                "objetivo_teste": caso.get("objetivo_teste", ""),
                "medida": caso["objeto_nome"],
                "mudanca": f"{caso['table']}[{caso['old_name']}] → [{caso['new_name']}]",
                "provedor": llm_provider.value,
                "modelo": llm_model,
                "expressao_original": caso["expressao_original"],
                "gabarito": caso["gabarito"],
                "expressao_gerada": expressao_gerada,
                "acuracia_exata": acuracia_exata,
                "acuracia_parcial": acuracia_parcial,
                "tempo_segundos": tempo,
                "erro": erro,
                "timestamp": datetime.now().isoformat(),
            }
            
            resultados.append(resultado)
            
            logger.info("caso_concluido", 
                caso_id=caso["id"],
                acuracia=acuracia_exata,
                tempo=f"{tempo:.2f}s"
            )
            
            # Delay preventivo para Google Gemini (rate limit: 5 req/min)
            # Aguarda 13s entre requisições para evitar bater no limite
            if llm_provider == LLMProvider.GOOGLE and i < len(casos):
                await asyncio.sleep(13)
        
        logger.info("experimento_dinamico_concluido", total_casos=len(resultados))
        return resultados
    
    def _build_impact_analysis(self, caso: Dict[str, Any]) -> ImpactAnalysis:
        """Constrói ImpactAnalysis a partir do caso de teste."""

        # Objeto alvo da mudança (coluna que está sendo renomeada)
        target_object = SemanticObject(
            object_type=ObjectType.COLUMN,
            name=caso["old_name"],
            table_name=caso["table"],
        )

        # Objeto semântico impactado (medida que será refatorada)
        obj = SemanticObject(
            object_type=caso["objeto_tipo"],
            name=caso["objeto_nome"],
            table_name=caso.get("objeto_tabela"),
            expression=caso["expressao_original"],
        )

        # Impacto direto: a medida depende da coluna renomeada
        impact = ImpactedObject(
            object=obj,
            impact_type="direct",
            original_expression=caso["expressao_original"],
            suggested_expression=caso["gabarito"],
            requires_manual_review=False,
            notes=f"Renomear {caso['table']}[{caso['old_name']}] para [{caso['new_name']}]",
        )

        return ImpactAnalysis(
            change_type=caso["change_type"],
            target_object=target_object,
            new_value=caso["new_name"],
            direct_impacts=[impact],
            cascade_impacts=[],
            relationship_impacts=[],
        )
    
    def _calcular_acuracia_exata(self, gabarito: str, gerada: str) -> bool:
        """Acurácia exata: expressões idênticas (normalizadas)."""
        return self._normalizar(gabarito) == self._normalizar(gerada)
    
    def _calcular_acuracia_parcial(self, gabarito: str, gerada: str) -> float:
        """
        Acurácia parcial: similaridade de tokens entre expressões.
        Retorna valor entre 0.0 e 1.0.
        """
        tokens_gab = set(self._tokenizar(gabarito))
        tokens_ger = set(self._tokenizar(gerada))
        
        if not tokens_gab and not tokens_ger:
            return 1.0
        if not tokens_gab or not tokens_ger:
            return 0.0
        
        intersecao = len(tokens_gab & tokens_ger)
        uniao = len(tokens_gab | tokens_ger)
        
        return intersecao / uniao if uniao > 0 else 0.0
    
    def _normalizar(self, expression: str) -> str:
        """Normaliza expressão DAX para comparação."""
        # Remove espaços extras, quebras de linha, case insensitive
        normalized = re.sub(r'\s+', ' ', expression.strip().upper())
        return normalized
    
    def _tokenizar(self, expression: str) -> List[str]:
        """Tokeniza expressão DAX em palavras/símbolos."""
        # Separa por espaços, vírgulas, parênteses, colchetes
        tokens = re.findall(r'\w+|\[|\]|\(|\)|,', expression.upper())
        return tokens


def gerar_relatorio_resumo(resultados: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Gera relatório resumo do experimento dinâmico.
    """
    total = len(resultados)
    acertos_exatos = sum(1 for r in resultados if r["acuracia_exata"])
    erros = sum(1 for r in resultados if r["erro"])
    tempo_medio = sum(r["tempo_segundos"] for r in resultados) / total if total > 0 else 0
    acuracia_parcial_media = sum(r["acuracia_parcial"] for r in resultados) / total if total > 0 else 0
    
    return {
        "total_casos": total,
        "acertos_exatos": acertos_exatos,
        "taxa_acuracia_exata": acertos_exatos / total if total > 0 else 0,
        "taxa_acuracia_parcial": acuracia_parcial_media,
        "erros": erros,
        "taxa_erro": erros / total if total > 0 else 0,
        "tempo_medio_segundos": tempo_medio,
        "timestamp": datetime.now().isoformat(),
    }
