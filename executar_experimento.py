#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experimento Completo - PBI Refactor Agent
TCC - Isabella da Silva Moura | FAETERJ 2026

Testa o agente em DUAS FASES, contra um modelo .pbit REAL:

  FASE 1 — ANÁLISE DE IMPACTO (sem LLM, só grafo de dependências)
      Para os 5 tipos de mudança (rename_column, rename_table, rename_measure,
      delete_column, delete_table), verifica se ImpactAnalyzer.analyze()
      encontra corretamente os objetos impactados (medida que referencia a
      coluna/tabela/medida alvo). Reusa o ImpactAnalyzer real do agente
      (src/pbi_refactor_agent/discovery/impact_analyzer.py) — não reimplementa
      nada, só chama e compara contra o gabarito (a medida que sabemos que
      referencia o alvo, porque foi ela que usamos para gerar o caso).

  FASE 2 — APLICAÇÃO
      - Para rename_column / rename_table / rename_measure: chama
        DAXRefactor.refactor() (LLM) e compara a expressão gerada com o
        gabarito por substituição textual (igual ao experimento anterior).
      - Para delete_column / delete_table: a aplicação automática correta
        é RECUSAR quando há dependência ativa. Sucesso = o ImpactAnalyzer
        sinalizou requires_manual_review=True para o(s) objeto(s) impactado(s)
        (ou seja, o agente bloqueou a aplicação, não tentou "adivinhar" uma
        correção). NÃO chama o LLM para delete_* nesta fase — o bloqueio é
        decidido pela análise de impacto da Fase 1, não por geração de texto.

USO:
    python executar_experimento.py gerar "data\\modelo.pbit" --max-casos 8
    -> revise data\\candidatos_revisao.json (igual antes)
    python executar_experimento.py executar "data\\modelo.pbit" --provider groq --model llama-3.3-70b-versatile

Os resultados ficam em data\\experimento_completo_resultados.json, com
métricas separadas por fase e por tipo de mudança.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "experiments"))

from pbi_refactor_agent.config import LLMProvider, get_settings
from pbi_refactor_agent.discovery import ImpactAnalyzer
from pbi_refactor_agent.models import ChangeType, ProposedChange
from pbi_refactor_agent.refactor import DAXRefactor
from pbi_refactor_agent.utils.pbix_extractor import extract_model, load_model_into_graph

from experimento_dinamico import ExperimentoDinamico


# ============================================================================
# SETUP (reusa a mesma sequência do app.py)
# ============================================================================

def montar_experimento(pbit_path: str) -> ExperimentoDinamico:
    print(f"📂 Extraindo modelo de: {pbit_path}")
    metadata = extract_model(pbit_path)
    graph = load_model_into_graph(metadata)
    print(f"✅ Modelo extraído: {metadata.summary['business_tables']} tabelas, "
          f"{metadata.summary['total_measures']} medidas")
    dax_refactor = DAXRefactor(settings=get_settings())
    return ExperimentoDinamico(metadata=metadata, graph=graph, dax_refactor=dax_refactor)


# ============================================================================
# ETAPA "gerar" — inalterada (reusa exportar_candidatos_para_revisao já existente)
# ============================================================================

def etapa_gerar(args):
    experimento = montar_experimento(args.pbit_path)
    casos = experimento.gerar_todos_os_tipos(max_casos_por_tipo=args.max_casos)
    if not casos:
        print("❌ Nenhum caso gerado. Verifique se há medidas DAX referenciando colunas/tabelas no modelo.")
        sys.exit(1)
    experimento.exportar_candidatos_para_revisao(casos, output_path=args.revisao_path)


# ============================================================================
# FASE 1 — ANÁLISE DE IMPACTO (sem LLM)
# ============================================================================

def _change_type_from_str(tipo_str: str) -> ChangeType:
    mapa = {
        "rename_column": ChangeType.RENAME_COLUMN,
        "rename_table": ChangeType.RENAME_TABLE,
        "rename_measure": ChangeType.RENAME_MEASURE,
        "delete_column": ChangeType.DELETE_COLUMN,
        "delete_table": ChangeType.DELETE_TABLE,
    }
    return mapa[tipo_str]


def testar_fase1_impacto(caso: Dict[str, Any], analyzer: ImpactAnalyzer) -> Dict[str, Any]:
    """
    Testa se o ImpactAnalyzer real do agente encontra corretamente o objeto
    impactado (a medida que sabemos que referencia o alvo, pois foi ela que
    usamos para construir o caso de teste).

    Critério de acerto: o nome da medida esperada (caso['objeto_nome']) está
    entre os objetos retornados em direct_impacts ou cascade_impacts.
    """
    ct = _change_type_from_str(caso["change_type"] if isinstance(caso["change_type"], str) else caso["change_type"].value)

    change = ProposedChange(
        change_type=ct,
        table_name=caso["table"] if ct != ChangeType.RENAME_TABLE else None,
        object_name=caso["old_name"],
        new_value=caso["new_name"] or None,
    )

    try:
        impact = analyzer.analyze(change)
    except Exception as e:
        return {
            "fase1_sucesso": False,
            "fase1_erro": str(e),
            "fase1_objetos_encontrados": [],
            "fase1_requires_manual_review": None,
        }

    nomes_encontrados = [
        imp.object.name
        for imp in (impact.direct_impacts + impact.cascade_impacts)
    ]
    medida_esperada = caso["objeto_nome"]
    encontrou_medida_esperada = medida_esperada in nomes_encontrados

    return {
        "fase1_sucesso": encontrou_medida_esperada,
        "fase1_erro": None,
        "fase1_objetos_encontrados": nomes_encontrados,
        "fase1_total_impactados": impact.total_impacted,
        "fase1_requires_manual_review": impact.requires_manual_review,
    }


# ============================================================================
# FASE 2 — APLICAÇÃO
# ============================================================================

def _normalizar(expr: str) -> str:
    import re
    return re.sub(r"\s+", " ", (expr or "").strip().upper())


async def testar_fase2_aplicacao_rename(
    caso: Dict[str, Any],
    fase1_impact_analysis,
    dax_refactor: DAXRefactor,
    llm_provider: LLMProvider,
    llm_model: str,
) -> Dict[str, Any]:
    """
    Para rename_*: chama o DAXRefactor real (LLM) e compara com o gabarito
    (substituição textual), exatamente como no experimento anterior.
    """
    inicio = datetime.now()
    try:
        result = await dax_refactor.refactor(
            impact_analysis=fase1_impact_analysis,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        tempo = (datetime.now() - inicio).total_seconds()
        if result.items and result.items[0].refactored_expression:
            gerada = result.items[0].refactored_expression
        else:
            gerada = ""
    except Exception as e:
        gerada = ""
        tempo = (datetime.now() - inicio).total_seconds()
        return {
            "fase2_sucesso": False,
            "fase2_erro": str(e),
            "fase2_expressao_gerada": "",
            "fase2_tempo_segundos": tempo,
        }

    gabarito = caso["gabarito"]
    acerto = _normalizar(gabarito) == _normalizar(gerada)

    return {
        "fase2_sucesso": acerto,
        "fase2_erro": None,
        "fase2_expressao_gerada": gerada,
        "fase2_tempo_segundos": tempo,
    }


def testar_fase2_aplicacao_delete(fase1_resultado: Dict[str, Any]) -> Dict[str, Any]:
    """
    Para delete_*: a aplicação correta é RECUSAR quando há dependência ativa.
    Não chama o LLM aqui — usa o que a Fase 1 (ImpactAnalyzer) já decidiu.

    Sucesso = requires_manual_review == True, ou seja, o agente identificou
    a dependência e bloqueou a aplicação automática (comportamento esperado
    e seguro), em vez de tentar gerar uma "correção" que romperia a lógica
    de negócio.
    """
    bloqueou_corretamente = fase1_resultado.get("fase1_requires_manual_review") is True
    return {
        "fase2_sucesso": bloqueou_corretamente,
        "fase2_erro": None,
        "fase2_expressao_gerada": None,
        "fase2_tempo_segundos": 0.0,
        "fase2_observacao": (
            "Aplicação corretamente bloqueada (dependência ativa detectada)."
            if bloqueou_corretamente
            else "Aplicação NÃO foi bloqueada — possível falha de segurança."
        ),
    }


# ============================================================================
# ORQUESTRAÇÃO DA ETAPA "executar"
# ============================================================================

async def etapa_executar(args):
    experimento = montar_experimento(args.pbit_path)
    casos_aprovados = experimento.filtrar_aprovados(revisao_path=args.revisao_path)
    if not casos_aprovados:
        print("❌ Nenhum candidato aprovado em", args.revisao_path)
        sys.exit(1)

    analyzer = ImpactAnalyzer(experimento.graph, metadata=experimento.metadata)
    llm_provider = LLMProvider(args.provider)

    resultados = []
    print(f"\n🔬 Executando {len(casos_aprovados)} caso(s) em 2 fases...\n")

    for i, caso in enumerate(casos_aprovados, 1):
        caso_id = caso["id"]
        tipo = caso["change_type"] if isinstance(caso["change_type"], str) else caso["change_type"].value
        print(f"  [{i}/{len(casos_aprovados)}] {caso_id} ({tipo})")

        # ---- FASE 1: Análise de Impacto (sempre, para os 5 tipos) ----
        fase1 = testar_fase1_impacto(caso, analyzer)
        print(f"      Fase 1 (impacto): {'✅' if fase1['fase1_sucesso'] else '❌'}")

        # Reconstroi o ImpactAnalysis completo (precisamos dele para a Fase 2 de rename)
        ct = _change_type_from_str(tipo)
        change = ProposedChange(
            change_type=ct,
            table_name=caso["table"] if ct != ChangeType.RENAME_TABLE else None,
            object_name=caso["old_name"],
            new_value=caso["new_name"] or None,
        )
        impact_analysis_completo = analyzer.analyze(change)

        # ---- FASE 2: Aplicação ----
        if tipo in ("rename_column", "rename_table", "rename_measure"):
            fase2 = await testar_fase2_aplicacao_rename(
                caso, impact_analysis_completo, experimento.dax_refactor, llm_provider, args.model
            )
        else:  # delete_column, delete_table
            fase2 = testar_fase2_aplicacao_delete(fase1)

        print(f"      Fase 2 (aplicação): {'✅' if fase2['fase2_sucesso'] else '❌'}")

        resultados.append({
            "caso_id": caso_id,
            "tipo_mudanca": tipo,
            "descricao": caso.get("descricao", ""),
            **fase1,
            **fase2,
        })

    # ---- Resumo consolidado ----
    from collections import defaultdict
    por_tipo = defaultdict(lambda: {"fase1_ok": 0, "fase2_ok": 0, "total": 0})
    for r in resultados:
        t = r["tipo_mudanca"]
        por_tipo[t]["total"] += 1
        if r["fase1_sucesso"]:
            por_tipo[t]["fase1_ok"] += 1
        if r["fase2_sucesso"]:
            por_tipo[t]["fase2_ok"] += 1

    resumo_por_tipo = {
        tipo: {
            "total": v["total"],
            "fase1_acuracia": v["fase1_ok"] / v["total"] if v["total"] else 0.0,
            "fase2_acuracia": v["fase2_ok"] / v["total"] if v["total"] else 0.0,
        }
        for tipo, v in por_tipo.items()
    }

    total = len(resultados)
    fase1_ok_total = sum(1 for r in resultados if r["fase1_sucesso"])
    fase2_ok_total = sum(1 for r in resultados if r["fase2_sucesso"])

    output_data = {
        "metadata_experimento": {
            "data_execucao": datetime.now().isoformat(),
            "pbit_origem": args.pbit_path,
            "provedor_llm": args.provider,
            "modelo_llm": args.model,
            "fluxo": "duas_fases (analise_impacto + aplicacao)",
        },
        "resumo_geral": {
            "total_casos": total,
            "fase1_acertos": fase1_ok_total,
            "fase1_acuracia": fase1_ok_total / total if total else 0.0,
            "fase2_acertos": fase2_ok_total,
            "fase2_acuracia": fase2_ok_total / total if total else 0.0,
        },
        "resumo_por_tipo": resumo_por_tipo,
        "casos_detalhados": resultados,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'='*60}")
    print("📊 RESUMO GERAL")
    print(f"{'='*60}")
    print(f"FASE 1 (Análise de Impacto): {fase1_ok_total}/{total} = {fase1_ok_total/total*100:.1f}%")
    print(f"FASE 2 (Aplicação):          {fase2_ok_total}/{total} = {fase2_ok_total/total*100:.1f}%")
    print(f"\nPor tipo de mudança:")
    for tipo, v in resumo_por_tipo.items():
        print(f"  {tipo:<18} Fase1={v['fase1_acuracia']*100:5.1f}%  Fase2={v['fase2_acuracia']*100:5.1f}%  (n={v['total']})")
    print(f"\n💾 Resultados salvos em: {out.resolve()}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Experimento de 2 fases: Análise de Impacto + Aplicação")
    sub = parser.add_subparsers(dest="etapa", required=True)

    p_gerar = sub.add_parser("gerar", help="Etapa 1: gerar candidatos (5 tipos) e exportar para revisão")
    p_gerar.add_argument("pbit_path")
    p_gerar.add_argument("--max-casos", type=int, default=8,
                          help="Número de casos a gerar POR TIPO de mudança (default: 8)")
    p_gerar.add_argument("--revisao-path", default="data/candidatos_revisao.json")

    p_exec = sub.add_parser("executar", help="Etapa 2: testar Fase 1 (impacto) + Fase 2 (aplicação) nos aprovados")
    p_exec.add_argument("pbit_path")
    p_exec.add_argument("--provider", default="groq", choices=["groq", "openai", "google", "anthropic"])
    p_exec.add_argument("--model", default="llama-3.3-70b-versatile")
    p_exec.add_argument("--revisao-path", default="data/candidatos_revisao.json")
    p_exec.add_argument("--output", default="data/experimento_completo_resultados.json")

    args = parser.parse_args()
    if args.etapa == "gerar":
        etapa_gerar(args)
    else:
        asyncio.run(etapa_executar(args))


if __name__ == "__main__":
    main()