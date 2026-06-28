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
import json
import re
from datetime import datetime
from pathlib import Path
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
        
        for item in todas_medidas:  # Analisa TODAS as medidas (ordenadas por complexidade desc.)
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
    
    def exportar_candidatos_para_revisao(
        self,
        casos: List[Dict[str, Any]],
        output_path: str = "data/candidatos_revisao.json",
    ) -> str:
        """
        [FLUXO HÍBRIDO] Exporta os casos candidatos gerados por gerar_casos_de_teste()
        para um JSON legível, para revisão humana ANTES de rodar contra o LLM.

        Cada candidato vem com um campo "aprovado": true por padrão — edite manualmente
        para "false" os que quiser descartar (ex.: redundantes, pouco representativos),
        e ajuste "gabarito" à mão se a substituição automática (regex) parecer incorreta
        para expressões complexas (VAR/RETURN, aspas em nomes de tabela, etc.).

        Depois de revisar, chame filtrar_aprovados() com o caminho deste arquivo.
        """
        candidatos = []
        for caso in casos:
            if caso["new_name"]:
                mudanca_str = f"{caso['table']}[{caso['old_name']}] -> [{caso['new_name']}]"
            else:
                mudanca_str = f"DELETE {caso['table']}[{caso['old_name']}]"

            candidatos.append({
                "id": caso["id"],
                "aprovado": True,  # mude para false para descartar este candidato
                "tipo_mudanca": caso["change_type"].value if hasattr(caso["change_type"], "value") else str(caso["change_type"]),
                "medida": f"{caso['objeto_tabela']}[{caso['objeto_nome']}]",
                "mudanca": mudanca_str,
                "expressao_original": caso["expressao_original"],
                "gabarito_gerado_automaticamente": caso["gabarito"],
                # Para delete_*, gabarito é None por design (requer revisão manual,
                # não há "expressão corrigida"). Não edite este campo para deleções.
                "gabarito_revisado": caso["gabarito"],
                "_caso_completo_original": caso,  # preserva tudo para reconstrução posterior
            })

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(candidatos, f, ensure_ascii=False, indent=2, default=str)

        logger.info("candidatos_exportados", total=len(candidatos), path=output_path)
        print(f"\n📤 {len(candidatos)} candidato(s) exportado(s) para: {output_path}")
        print("   Revise o arquivo: marque \"aprovado\": false para descartar,")
        print("   ou edite \"gabarito_revisado\" se a substituição automática estiver incorreta.")
        print("   Depois, chame filtrar_aprovados() apontando para este arquivo.")
        return output_path

    def filtrar_aprovados(self, revisao_path: str = "data/candidatos_revisao.json") -> List[Dict[str, Any]]:
        """
        [FLUXO HÍBRIDO] Lê o JSON revisado por humano e reconstrói a lista de casos
        de teste, mantendo apenas os marcados como "aprovado": true e aplicando
        qualquer edição manual feita em "gabarito_revisado".
        """
        with open(revisao_path, "r", encoding="utf-8") as f:
            candidatos = json.load(f)

        casos_aprovados = []
        for cand in candidatos:
            if not cand.get("aprovado", False):
                continue
            caso = cand["_caso_completo_original"]
            # Aplica o gabarito revisado manualmente (se a pessoa editou)
            caso["gabarito"] = cand.get("gabarito_revisado", caso["gabarito"])
            casos_aprovados.append(caso)

        logger.info("candidatos_filtrados", total_aprovados=len(casos_aprovados), total_original=len(candidatos))
        print(f"\n✅ {len(casos_aprovados)}/{len(candidatos)} candidato(s) aprovado(s) para execução.")
        return casos_aprovados

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

    # ========================================================================
    # RENAME_TABLE
    # ========================================================================

    def gerar_casos_rename_table(self, max_casos: int = 8) -> List[Dict[str, Any]]:
        """
        Gera casos de teste de renomeio de TABELA.

        Estratégia: para cada tabela de negócio que aparece em pelo menos uma
        expressão DAX de alguma medida, gera um caso "renomear TabelaX -> TabelaXUpdated"
        usando a primeira medida que a referencia como objeto impactado.
        """
        logger.info("gerando_casos_rename_table", max_casos=max_casos)
        casos = []
        caso_id = 1
        tabelas_usadas = set()

        print(f"\n🔎 Buscando tabelas referenciadas em expressões DAX...")

        for table in self.metadata.business_tables:
            for measure in table.measures:
                if len(casos) >= max_casos:
                    break
                if not measure.is_hidden and measure.expression:
                    tabelas_refs = self._extrair_tabelas_referenciadas(measure.expression)
                    for tabela_ref in tabelas_refs:
                        if tabela_ref in tabelas_usadas:
                            continue
                        if len(casos) >= max_casos:
                            break

                        novo_nome = f"{tabela_ref}Updated"
                        gabarito = self._calcular_gabarito_tabela(
                            measure.expression, tabela_ref, novo_nome
                        )

                        caso = {
                            "id": f"RT{caso_id:02d}",
                            "cenario": "Renomeio de Tabela",
                            "descricao": f"Renomear tabela {tabela_ref} → {novo_nome} (afeta {measure.name})",
                            "objetivo_teste": "Validar se o agente atualiza corretamente as referências de tabela em expressões DAX.",
                            "change_type": ChangeType.RENAME_TABLE,
                            "table": tabela_ref,
                            "old_name": tabela_ref,
                            "new_name": novo_nome,
                            "objeto_nome": measure.name,
                            "objeto_tipo": ObjectType.MEASURE,
                            "objeto_tabela": table.name,
                            "expressao_original": measure.expression,
                            "gabarito": gabarito,
                            "medida_original": {
                                "name": measure.name,
                                "table": table.name,
                                "complexity": measure.complexity,
                            },
                        }
                        casos.append(caso)
                        tabelas_usadas.add(tabela_ref)
                        caso_id += 1
                        print(f"  ✓ {caso['id']}: {tabela_ref} → {novo_nome} (via {measure.name})")

        print(f"📝 {len(casos)} caso(s) de renomeio de tabela gerado(s).")
        logger.info("casos_rename_table_gerados", total=len(casos))
        return casos

    def _extrair_tabelas_referenciadas(self, expression: str) -> List[str]:
        """Extrai nomes de tabelas referenciadas em uma expressão DAX (Tabela[...] ou 'Tabela'[...])."""
        pattern = r"(?:'([^']+)'|(\w+))\["
        matches = re.finditer(pattern, expression)
        tabelas = []
        seen = set()
        for match in matches:
            tabela = match.group(1) if match.group(1) else match.group(2)
            if tabela not in seen and self._tabela_existe(tabela):
                tabelas.append(tabela)
                seen.add(tabela)
        return tabelas

    def _tabela_existe(self, table_name: str) -> bool:
        """Verifica se a tabela existe no modelo (case-insensitive)."""
        table_name_lower = table_name.lower()
        for table in self.metadata.tables:
            if table.name.lower() == table_name_lower:
                return True
        return False

    def _calcular_gabarito_tabela(self, expression: str, old_table: str, new_table: str) -> str:
        """
        Calcula a expressão esperada após renomeação de uma TABELA.

        Substitui Tabela[...] e 'Tabela'[...] por NovaTabela[...] / 'NovaTabela'[...],
        preservando o formato de aspas original de cada ocorrência.
        """
        # Caso com aspas simples: 'TabelaAntiga'[
        pattern_aspas = rf"'{re.escape(old_table)}'\["
        gabarito = re.sub(pattern_aspas, f"'{new_table}'[", expression)
        # Caso sem aspas: TabelaAntiga[ (boundary de palavra para não substituir substring de outro nome)
        pattern_sem_aspas = rf"\b{re.escape(old_table)}\["
        gabarito = re.sub(pattern_sem_aspas, f"{new_table}[", gabarito)
        return gabarito

    # ========================================================================
    # RENAME_MEASURE
    # ========================================================================

    def gerar_casos_rename_measure(self, max_casos: int = 8) -> List[Dict[str, Any]]:
        """
        Gera casos de teste de renomeio de MEDIDA.

        Estratégia: identifica medidas que são referenciadas (via [NomeMedida])
        dentro da expressão de OUTRA medida, e gera um caso "renomear a medida
        referenciada", usando a medida que a referencia como objeto impactado.
        """
        logger.info("gerando_casos_rename_measure", max_casos=max_casos)
        casos = []
        caso_id = 1
        medidas_usadas = set()

        # Nomes de todas as medidas do modelo, para validar referências encontradas
        nomes_medidas = {
            m.name for t in self.metadata.business_tables for m in t.measures
        }

        print(f"\n🔎 Buscando medidas referenciadas dentro de outras medidas...")

        for table in self.metadata.business_tables:
            for measure in table.measures:
                if len(casos) >= max_casos:
                    break
                if measure.is_hidden or not measure.expression:
                    continue

                medidas_refs = self._extrair_medidas_referenciadas(
                    measure.expression, nomes_medidas, excluir=measure.name
                )

                for medida_ref in medidas_refs:
                    if medida_ref in medidas_usadas:
                        continue
                    if len(casos) >= max_casos:
                        break

                    novo_nome = f"{medida_ref} Updated"
                    gabarito = self._calcular_gabarito_medida(
                        measure.expression, medida_ref, novo_nome
                    )

                    caso = {
                        "id": f"RM{caso_id:02d}",
                        "cenario": "Renomeio de Medida",
                        "descricao": f"Renomear medida [{medida_ref}] → [{novo_nome}] (afeta {measure.name})",
                        "objetivo_teste": "Validar se o agente atualiza corretamente as referências a medidas em expressões DAX.",
                        "change_type": ChangeType.RENAME_MEASURE,
                        "table": table.name,
                        "old_name": medida_ref,
                        "new_name": novo_nome,
                        "objeto_nome": measure.name,
                        "objeto_tipo": ObjectType.MEASURE,
                        "objeto_tabela": table.name,
                        "expressao_original": measure.expression,
                        "gabarito": gabarito,
                        "medida_original": {
                            "name": measure.name,
                            "table": table.name,
                            "complexity": measure.complexity,
                        },
                    }
                    casos.append(caso)
                    medidas_usadas.add(medida_ref)
                    caso_id += 1
                    print(f"  ✓ {caso['id']}: [{medida_ref}] → [{novo_nome}] (via {measure.name})")

        print(f"📝 {len(casos)} caso(s) de renomeio de medida gerado(s).")
        logger.info("casos_rename_measure_gerados", total=len(casos))
        return casos

    def _extrair_medidas_referenciadas(
        self, expression: str, nomes_medidas: set, excluir: str
    ) -> List[str]:
        """
        Extrai referências a medidas (sintaxe [NomeMedida], sem prefixo de tabela)
        que correspondem a medidas reais conhecidas no modelo.
        """
        # [NomeMedida] sem tabela antes (não precedido por ' ou palavra+[)
        pattern = r"(?<![\w'])\[([^\]]+)\]"
        matches = re.finditer(pattern, expression)
        refs = []
        seen = set()
        for match in matches:
            nome = match.group(1)
            if nome == excluir or nome in seen:
                continue
            if nome in nomes_medidas:
                refs.append(nome)
                seen.add(nome)
        return refs

    def _calcular_gabarito_medida(self, expression: str, old_measure: str, new_measure: str) -> str:
        """Calcula a expressão esperada após renomeação de uma MEDIDA (substitui [Antiga] por [Nova])."""
        pattern = rf"\[{re.escape(old_measure)}\]"
        replacement = f"[{new_measure}]"
        return re.sub(pattern, replacement, expression)

    # ========================================================================
    # DELETE_COLUMN
    # ========================================================================

    def gerar_casos_delete_column(self, max_casos: int = 8) -> List[Dict[str, Any]]:
        """
        Gera casos de teste de DELEÇÃO de coluna.

        Estratégia: reusa a mesma extração de referências de coluna do
        rename_column, mas sem gabarito de substituição — deleção não tem
        "expressão corrigida automática", exige revisão manual (mesmo
        comportamento do app.py: new_name fica vazio/None).
        """
        logger.info("gerando_casos_delete_column", max_casos=max_casos)
        casos = []
        caso_id = 1
        colunas_usadas = set()

        print(f"\n🔎 Buscando colunas ativamente referenciadas para teste de deleção...")

        todas_medidas = []
        for table in self.metadata.business_tables:
            for measure in table.measures:
                if not measure.is_hidden and measure.expression:
                    todas_medidas.append({"table": table.name, "measure": measure})

        for item in todas_medidas:
            if len(casos) >= max_casos:
                break
            table_name = item["table"]
            measure = item["measure"]
            expression = measure.expression

            colunas_refs = self._extrair_referencias_colunas(expression, table_name)
            for col_ref in colunas_refs:
                key = f"{col_ref['table']}.{col_ref['column']}"
                if key in colunas_usadas:
                    continue
                if len(casos) >= max_casos:
                    break

                caso = {
                    "id": f"DC{caso_id:02d}",
                    "cenario": "Deleção de Coluna",
                    "descricao": f"Deletar {col_ref['table']}[{col_ref['column']}] (afeta {measure.name})",
                    "objetivo_teste": "Validar se o agente identifica corretamente o impacto de deletar uma coluna ativamente referenciada, sinalizando revisão manual.",
                    "change_type": ChangeType.DELETE_COLUMN,
                    "table": col_ref["table"],
                    "old_name": col_ref["column"],
                    "new_name": "",  # Deleção não tem novo nome
                    "objeto_nome": measure.name,
                    "objeto_tipo": ObjectType.MEASURE,
                    "objeto_tabela": table_name,
                    "expressao_original": expression,
                    # Sem substituição automática possível: gabarito = None ⇒ requer revisão manual,
                    # replicando o comportamento real do agente para este tipo de mudança.
                    "gabarito": None,
                    "medida_original": {
                        "name": measure.name,
                        "table": table_name,
                        "complexity": measure.complexity,
                    },
                }
                casos.append(caso)
                colunas_usadas.add(key)
                caso_id += 1
                print(f"  ✓ {caso['id']}: DELETE {col_ref['table']}[{col_ref['column']}] (via {measure.name})")

        print(f"📝 {len(casos)} caso(s) de deleção de coluna gerado(s).")
        logger.info("casos_delete_column_gerados", total=len(casos))
        return casos

    # ========================================================================
    # DELETE_TABLE
    # ========================================================================

    def gerar_casos_delete_table(self, max_casos: int = 8) -> List[Dict[str, Any]]:
        """
        Gera casos de teste de DELEÇÃO de tabela inteira.

        Estratégia: mistura tabelas "centrais" (muitas medidas/relacionamentos
        apontando para ela) com tabelas "isoladas" (poucas referências),
        para cobrir tanto cascata grande quanto pequena. Todos os casos têm
        impacto real (a tabela é referenciada por pelo menos uma medida).
        """
        logger.info("gerando_casos_delete_table", max_casos=max_casos)
        casos = []
        caso_id = 1

        # Conta, para cada tabela, quantas medidas (de qualquer tabela) a referenciam
        contagem_referencias: Dict[str, int] = {}
        medida_exemplo_por_tabela: Dict[str, Any] = {}

        for table in self.metadata.business_tables:
            for measure in table.measures:
                if measure.is_hidden or not measure.expression:
                    continue
                tabelas_refs = self._extrair_tabelas_referenciadas(measure.expression)
                for tabela_ref in tabelas_refs:
                    contagem_referencias[tabela_ref] = contagem_referencias.get(tabela_ref, 0) + 1
                    if tabela_ref not in medida_exemplo_por_tabela:
                        medida_exemplo_por_tabela[tabela_ref] = {"table": table.name, "measure": measure}

        if not contagem_referencias:
            print("⚠️  Nenhuma tabela com referência ativa encontrada para delete_table.")
            return casos

        # Ordena tabelas por nº de referências (desc) — as primeiras são "centrais", as últimas "isoladas"
        tabelas_ordenadas = sorted(contagem_referencias.items(), key=lambda x: x[1], reverse=True)

        n_centrais = max_casos // 2
        n_isoladas = max_casos - n_centrais
        selecionadas = tabelas_ordenadas[:n_centrais] + tabelas_ordenadas[-n_isoladas:]

        print(f"\n🔎 Selecionando {n_centrais} tabela(s) central(is) + {n_isoladas} isolada(s) para teste de deleção...")

        vistas = set()
        for tabela_nome, n_refs in selecionadas:
            if tabela_nome in vistas or len(casos) >= max_casos:
                continue
            vistas.add(tabela_nome)

            exemplo = medida_exemplo_por_tabela[tabela_nome]
            measure = exemplo["measure"]

            caso = {
                "id": f"DT{caso_id:02d}",
                "cenario": "Deleção de Tabela",
                "descricao": f"Deletar tabela {tabela_nome} ({n_refs} referência(s) em medidas) — afeta {measure.name}",
                "objetivo_teste": "Validar se o agente identifica corretamente o impacto de deletar uma tabela inteira, incluindo medidas e relacionamentos dependentes.",
                "change_type": ChangeType.DELETE_TABLE,
                "table": tabela_nome,
                "old_name": tabela_nome,
                "new_name": "",
                "objeto_nome": measure.name,
                "objeto_tipo": ObjectType.MEASURE,
                "objeto_tabela": exemplo["table"],
                "expressao_original": measure.expression,
                "gabarito": None,  # Deleção de tabela sempre requer revisão manual
                "medida_original": {
                    "name": measure.name,
                    "table": exemplo["table"],
                    "complexity": measure.complexity,
                },
                "n_referencias_na_tabela": n_refs,
            }
            casos.append(caso)
            caso_id += 1
            tipo_str = "CENTRAL" if n_refs >= tabelas_ordenadas[len(tabelas_ordenadas)//2][1] else "isolada"
            print(f"  ✓ {caso['id']}: DELETE TABLE {tabela_nome} [{tipo_str}, {n_refs} ref(s)] (via {measure.name})")

        print(f"📝 {len(casos)} caso(s) de deleção de tabela gerado(s).")
        logger.info("casos_delete_table_gerados", total=len(casos))
        return casos

    # ========================================================================
    # ORQUESTRAÇÃO: GERAR TODOS OS TIPOS DE UMA VEZ
    # ========================================================================

    def gerar_todos_os_tipos(self, max_casos_por_tipo: int = 8) -> List[Dict[str, Any]]:
        """
        Gera casos de teste para os 5 tipos de mudança suportados, na proporção
        max_casos_por_tipo cada (default 8+8+8+8+8 = 40 casos).

        rename_column reusa gerar_casos_de_teste() (já existente, sem alteração);
        os demais tipos usam os métodos gerar_casos_<tipo>() definidos acima.
        """
        casos_rename_column = self.gerar_casos_de_teste(max_casos=max_casos_por_tipo)
        casos_rename_table = self.gerar_casos_rename_table(max_casos=max_casos_por_tipo)
        casos_rename_measure = self.gerar_casos_rename_measure(max_casos=max_casos_por_tipo)
        casos_delete_column = self.gerar_casos_delete_column(max_casos=max_casos_por_tipo)
        casos_delete_table = self.gerar_casos_delete_table(max_casos=max_casos_por_tipo)

        todos = (
            casos_rename_column
            + casos_rename_table
            + casos_rename_measure
            + casos_delete_column
            + casos_delete_table
        )

        print(f"\n{'='*60}")
        print(f"📊 RESUMO GERAL — {len(todos)} caso(s) gerado(s) no total")
        print(f"{'='*60}")
        print(f"  Renomeio de coluna:  {len(casos_rename_column)}")
        print(f"  Renomeio de tabela:  {len(casos_rename_table)}")
        print(f"  Renomeio de medida:  {len(casos_rename_measure)}")
        print(f"  Deleção de coluna:   {len(casos_delete_column)}")
        print(f"  Deleção de tabela:   {len(casos_delete_table)}")

        logger.info(
            "todos_os_tipos_gerados",
            total=len(todos),
            rename_column=len(casos_rename_column),
            rename_table=len(casos_rename_table),
            rename_measure=len(casos_rename_measure),
            delete_column=len(casos_delete_column),
            delete_table=len(casos_delete_table),
        )
        return todos
    
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
                gabarito_none = caso.get("gabarito") is None
                if result.items and result.items[0].refactored_expression:
                    expressao_gerada = result.items[0].refactored_expression
                    erro = False
                elif gabarito_none:
                    # delete_column/delete_table: ausência de sugestão é o
                    # comportamento ESPERADO (requires_manual_review filtrou
                    # a chamada ao LLM em DAXRefactor.refactor()), não um erro.
                    expressao_gerada = ""
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
        """Constrói ImpactAnalysis a partir do caso de teste.

        Suporta os 5 tipos de mudança (rename_column, rename_table,
        rename_measure, delete_column, delete_table). O object_type do
        target_object varia conforme o tipo de mudança proposta.
        """
        ct = caso["change_type"]

        # Tipo do objeto-alvo da mudança varia conforme change_type
        if ct in (ChangeType.RENAME_TABLE, ChangeType.DELETE_TABLE):
            target_type = ObjectType.TABLE
        elif ct == ChangeType.RENAME_MEASURE:
            target_type = ObjectType.MEASURE
        else:  # RENAME_COLUMN, DELETE_COLUMN
            target_type = ObjectType.COLUMN

        target_object = SemanticObject(
            object_type=target_type,
            name=caso["old_name"],
            table_name=caso["table"],
        )

        # Objeto semântico impactado (medida que será refatorada/revisada)
        obj = SemanticObject(
            object_type=caso["objeto_tipo"],
            name=caso["objeto_nome"],
            table_name=caso.get("objeto_tabela"),
            expression=caso["expressao_original"],
        )

        gabarito = caso.get("gabarito")
        requer_revisao_manual = gabarito is None  # delete_column / delete_table

        if caso["new_name"]:
            nota = f"Renomear {caso['table']}[{caso['old_name']}] para [{caso['new_name']}]"
        else:
            nota = f"Deletar {caso['table']}[{caso['old_name']}] — requer revisão manual"

        impact = ImpactedObject(
            object=obj,
            impact_type="direct",
            original_expression=caso["expressao_original"],
            suggested_expression=gabarito,
            requires_manual_review=requer_revisao_manual,
            notes=nota,
        )

        return ImpactAnalysis(
            change_type=ct,
            target_object=target_object,
            new_value=caso["new_name"] or None,
            direct_impacts=[impact],
            cascade_impacts=[],
            relationship_impacts=[],
        )
    
    def _calcular_acuracia_exata(self, gabarito: Optional[str], gerada: str) -> bool:
        """
        Acurácia exata: expressões idênticas (normalizadas).

        Para casos sem gabarito automático (delete_column/delete_table),
        considera "correto" quando o agente NÃO sugeriu uma expressão (ou seja,
        corretamente sinalizou que requer revisão manual em vez de alucinar
        uma correção). Essa é a mesma noção de acurácia, adaptada ao fato de
        que deleção não tem "expressão corrigida" de referência.
        """
        if gabarito is None:
            return not gerada or not gerada.strip()
        return self._normalizar(gabarito) == self._normalizar(gerada)
    
    def _calcular_acuracia_parcial(self, gabarito: Optional[str], gerada: str) -> float:
        """
        Acurácia parcial: similaridade de tokens entre expressões.
        Retorna valor entre 0.0 e 1.0.

        Para casos sem gabarito (delete_*), retorna 1.0 se o agente também
        não gerou expressão (comportamento esperado/correto) e 0.0 caso
        contrário (o agente alucinou uma correção que não deveria existir).
        """
        if gabarito is None:
            return 1.0 if (not gerada or not gerada.strip()) else 0.0

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