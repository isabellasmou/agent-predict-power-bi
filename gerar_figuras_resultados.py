#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de Figuras de Resultados - PBI Refactor Agent
TCC - Isabella da Silva Moura | FAETERJ 2026

Lê o JSON de resultados gerado por experimento_completo.py e produz as
figuras de resultado do Capítulo 5, mantendo o mesmo estilo visual das
figuras conceituais já existentes (fundo branco, cores sólidas, 300 DPI).

USO:
    python gerar_figuras_resultados.py data\\experimento_completo_resultados.json

Gera, dentro de tcc_latex\\figuras_teste\\:
    fase1_acuracia_por_tipo.png      - acurácia da Análise de Impacto, por tipo
    fase2_acuracia_por_tipo.png      - acurácia da Aplicação, por tipo
    resumo_duas_fases.png            - Fase 1 vs Fase 2, barras agrupadas
    distribuicao_tempos_fase2.png    - distribuição de tempo (só LLM, rename_*)
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ============================================================================
# Paleta consistente com as figuras já existentes do TCC
# ============================================================================
COR_VERDE = "#4CAF50"
COR_AMARELO = "#FFC107"
COR_LARANJA = "#FF9800"
COR_AZUL = "#2196F3"
COR_VERMELHO = "#F87171"
COR_AZUL_ESCURO = "#1565C0"

# Cor por tipo de mudança (consistente nas 3 figuras de acurácia)
COR_POR_TIPO = {
    "rename_column": COR_VERDE,
    "rename_table": COR_AZUL,
    "rename_measure": COR_AMARELO,
    "delete_column": COR_LARANJA,
    "delete_table": COR_VERMELHO,
}

LABEL_POR_TIPO = {
    "rename_column": "Renomeio\nde Coluna",
    "rename_table": "Renomeio\nde Tabela",
    "rename_measure": "Renomeio\nde Medida",
    "delete_column": "Deleção\nde Coluna",
    "delete_table": "Deleção\nde Tabela",
}

# Ordem fixa de exibição em todos os gráficos
ORDEM_TIPOS = ["rename_column", "rename_table", "rename_measure", "delete_column", "delete_table"]


def carregar_resultados(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _tipos_presentes(resumo_por_tipo: dict) -> list:
    """Filtra ORDEM_TIPOS apenas para os tipos que de fato existem no resultado."""
    return [t for t in ORDEM_TIPOS if t in resumo_por_tipo]


# ============================================================================
# FIGURA 1: Acurácia da Fase 1 (Análise de Impacto) por tipo
# ============================================================================

def gerar_fase1_acuracia(resumo_por_tipo: dict, output_dir: Path):
    tipos = _tipos_presentes(resumo_por_tipo)
    labels = [LABEL_POR_TIPO[t] for t in tipos]
    valores = [resumo_por_tipo[t]["fase1_acuracia"] * 100 for t in tipos]
    cores = [COR_POR_TIPO[t] for t in tipos]
    media = sum(valores) / len(valores) if valores else 0

    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(labels, valores, color=cores, edgecolor="black", linewidth=1.5, alpha=0.85)
    ax.set_ylabel("Acurácia (%)", fontsize=13, weight="bold")
    ax.set_ylim(0, 115)
    ax.set_title("Fase 1 — Acurácia da Análise de Impacto por Tipo de Mudança",
                 fontsize=14, weight="bold", pad=15)
    ax.axhline(y=media, color="red", linestyle="--", linewidth=2.5,
               label=f"Média Geral ({media:.1f}%)")
    ax.legend(fontsize=11)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    for bar, val in zip(bars, valores):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=12, weight="bold")

    plt.tight_layout()
    out = output_dir / "fase1_acuracia_por_tipo.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"✅ {out.name}")


# ============================================================================
# FIGURA 2: Acurácia da Fase 2 (Aplicação) por tipo
# ============================================================================

def gerar_fase2_acuracia(resumo_por_tipo: dict, output_dir: Path):
    tipos = _tipos_presentes(resumo_por_tipo)
    labels = [LABEL_POR_TIPO[t] for t in tipos]
    valores = [resumo_por_tipo[t]["fase2_acuracia"] * 100 for t in tipos]
    cores = [COR_POR_TIPO[t] for t in tipos]
    media = sum(valores) / len(valores) if valores else 0

    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(labels, valores, color=cores, edgecolor="black", linewidth=1.5, alpha=0.85)
    ax.set_ylabel("Acurácia (%)", fontsize=13, weight="bold")
    ax.set_ylim(0, 115)
    ax.set_title("Fase 2 — Acurácia da Aplicação por Tipo de Mudança\n"
                 "(Renomeio: correção via LLM · Deleção: bloqueio correto por dependência)",
                 fontsize=13, weight="bold", pad=15)
    ax.axhline(y=media, color="red", linestyle="--", linewidth=2.5,
               label=f"Média Geral ({media:.1f}%)")
    ax.legend(fontsize=11)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    for bar, val in zip(bars, valores):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=12, weight="bold")

    plt.tight_layout()
    out = output_dir / "fase2_acuracia_por_tipo.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"✅ {out.name}")


# ============================================================================
# FIGURA 3: Resumo combinado — Fase 1 vs Fase 2, barras agrupadas
# ============================================================================

def gerar_resumo_duas_fases(resumo_por_tipo: dict, output_dir: Path):
    import numpy as np

    tipos = _tipos_presentes(resumo_por_tipo)
    labels = [LABEL_POR_TIPO[t] for t in tipos]
    fase1_vals = [resumo_por_tipo[t]["fase1_acuracia"] * 100 for t in tipos]
    fase2_vals = [resumo_por_tipo[t]["fase2_acuracia"] * 100 for t in tipos]

    x = np.arange(len(tipos))
    largura = 0.35

    fig, ax = plt.subplots(figsize=(13, 6.5))
    bars1 = ax.bar(x - largura / 2, fase1_vals, largura, label="Fase 1 — Análise de Impacto",
                   color=COR_AZUL, edgecolor="black", linewidth=1.3, alpha=0.85)
    bars2 = ax.bar(x + largura / 2, fase2_vals, largura, label="Fase 2 — Aplicação",
                   color=COR_VERDE, edgecolor="black", linewidth=1.3, alpha=0.85)

    ax.set_ylabel("Acurácia (%)", fontsize=13, weight="bold")
    ax.set_ylim(0, 115)
    ax.set_title("Resumo Comparativo — Fase 1 (Impacto) vs Fase 2 (Aplicação)",
                 fontsize=14, weight="bold", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(fontsize=11, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    for bars in (bars1, bars2):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 2,
                    f"{h:.0f}%", ha="center", va="bottom", fontsize=10, weight="bold")

    plt.tight_layout()
    out = output_dir / "resumo_duas_fases.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"✅ {out.name}")


# ============================================================================
# FIGURA 4: Distribuição de tempo de resposta (só Fase 2, casos com LLM)
# ============================================================================

def gerar_distribuicao_tempos(casos_detalhados: list, output_dir: Path):
    tipos_com_llm = {"rename_column", "rename_table", "rename_measure"}
    tempos = []
    ids = []
    for c in casos_detalhados:
        if c.get("tipo_mudanca") in tipos_com_llm:
            t = c.get("fase2_tempo_segundos")
            if t is not None and t > 0:
                tempos.append(t)
                ids.append(c["caso_id"])

    if not tempos:
        print("⚠️  Nenhum caso com tempo de LLM encontrado — pulando distribuicao_tempos_fase2.png")
        return

    pares = sorted(zip(ids, tempos), key=lambda p: p[1])
    ids_ord, tempos_ord = zip(*pares)

    media = sum(tempos) / len(tempos)

    faixas = {"< 1s": 0, "1-5s": 0, "5-10s": 0, "> 10s": 0}
    for t in tempos:
        if t < 1:
            faixas["< 1s"] += 1
        elif t < 5:
            faixas["1-5s"] += 1
        elif t < 10:
            faixas["5-10s"] += 1
        else:
            faixas["> 10s"] += 1
    total = len(tempos)
    faixas_pct = {k: v / total * 100 for k, v in faixas.items()}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    cores_barras = []
    for t in tempos_ord:
        if t < 1:
            cores_barras.append(COR_VERDE)
        elif t < 5:
            cores_barras.append(COR_AZUL)
        elif t < 10:
            cores_barras.append(COR_AMARELO)
        else:
            cores_barras.append(COR_VERMELHO)

    ax1.bar(range(len(tempos_ord)), tempos_ord, color=cores_barras,
            edgecolor="black", linewidth=1, alpha=0.85)
    ax1.set_xticks(range(len(ids_ord)))
    ax1.set_xticklabels(ids_ord, rotation=45, ha="right", fontsize=8)
    ax1.set_ylabel("Tempo de Resposta (s)", fontsize=12, weight="bold")
    ax1.set_xlabel("Caso de Teste", fontsize=12, weight="bold")
    ax1.set_title("Tempo de Resposta por Caso (Fase 2 — LLM)", fontsize=13, weight="bold")
    ax1.axhline(y=media, color="red", linestyle="--", linewidth=2, label=f"Média: {media:.2f}s")
    ax1.legend(fontsize=10)
    ax1.grid(axis="y", alpha=0.3, linestyle="--")

    labels_pizza = [f"{k}\n({v:.1f}%)" for k, v in faixas_pct.items() if faixas[k] > 0]
    valores_pizza = [v for k, v in faixas_pct.items() if faixas[k] > 0]
    cores_pizza = [COR_VERDE, COR_AZUL, COR_AMARELO, COR_VERMELHO][:len(valores_pizza)]

    ax2.pie(valores_pizza, labels=labels_pizza, colors=cores_pizza,
            autopct=lambda p: f"{int(round(p * total / 100))} casos",
            startangle=90, wedgeprops={"edgecolor": "black", "linewidth": 1.3})
    ax2.set_title("Distribuição por Faixa de Tempo", fontsize=13, weight="bold")

    plt.tight_layout()
    out = output_dir / "distribuicao_tempos_fase2.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"✅ {out.name}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Gera figuras de resultado a partir do JSON do experimento_completo.py")
    parser.add_argument("json_path", help="Caminho para experimento_completo_resultados.json")
    parser.add_argument("--output-dir", default="tcc_latex/figuras_teste",
                         help="Pasta de saída das figuras (default: tcc_latex/figuras_teste)")
    args = parser.parse_args()

    if not Path(args.json_path).exists():
        print(f"❌ Arquivo não encontrado: {args.json_path}")
        sys.exit(1)

    dados = carregar_resultados(args.json_path)
    resumo_por_tipo = dados.get("resumo_por_tipo", {})
    casos_detalhados = dados.get("casos_detalhados", [])

    if not resumo_por_tipo:
        print("❌ Campo 'resumo_por_tipo' não encontrado no JSON. Verifique se é o arquivo certo "
              "(gerado por experimento_completo.py, não o formato antigo).")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎨 Gerando figuras a partir de: {args.json_path}")
    print(f"📁 Saída: {output_dir}\n")

    gerar_fase1_acuracia(resumo_por_tipo, output_dir)
    gerar_fase2_acuracia(resumo_por_tipo, output_dir)
    gerar_resumo_duas_fases(resumo_por_tipo, output_dir)
    gerar_distribuicao_tempos(casos_detalhados, output_dir)

    print(f"\n{'='*60}")
    print("🎉 TODAS AS FIGURAS DE RESULTADO FORAM GERADAS")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()