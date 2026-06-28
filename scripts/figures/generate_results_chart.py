"""
Script para gerar gráficos dos resultados do experimento controlado.

Este script cria visualizações dos resultados de acurácia por cenário
baseados nos dados do arquivo experiments/resultados/resultado_20260505_211431_resumo.json

Uso:
    python generate_results_chart.py
    
Saída:
    tcc_latex/figuras/resultados_acuracia.png (300 DPI)
    tcc_latex/figuras/resultados_tempo.png (300 DPI)
"""

import matplotlib.pyplot as plt
import pandas as pd
import json
from pathlib import Path

def load_experiment_results():
    """Carrega resultados do experimento."""
    
    # Dados baseados em experiments/ANALISE_RESULTADOS.md
    data = {
        'Cenário': ['Rename\nMedida', 'Rename\nTabela', 'Rename\nColuna', 'Geral'],
        'Acurácia (%)': [100.0, 75.0, 71.4, 78.6],
        'Casos': [7, 4, 3, 14],
        'Corretos': [7, 3, 2, 11],
        'Tempo Médio (s)': [4.32, 5.18, 6.21, 4.96]
    }
    
    return pd.DataFrame(data)

def plot_accuracy_chart(df, output_path):
    """Gera gráfico de acurácia por cenário."""
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Cores por desempenho
    colors = ['#4CAF50', '#FFC107', '#FF5722', '#2196F3']
    
    # Criar barras
    bars = ax.bar(df['Cenário'], df['Acurácia (%)'], color=colors, edgecolor='black', linewidth=1.5)
    
    # Adicionar valores nas barras
    for bar, acuracia, casos, corretos in zip(bars, df['Acurácia (%)'], df['Casos'], df['Corretos']):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width()/2., 
            height + 2,
            f'{acuracia:.1f}%\n({corretos}/{casos})',
            ha='center', 
            va='bottom', 
            fontsize=12, 
            fontweight='bold'
        )
    
    # Configurações do gráfico
    ax.set_ylabel('Acurácia (%)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Cenário de Teste', fontsize=14, fontweight='bold')
    ax.set_title('Resultados do Experimento Controlado - Acurácia por Cenário', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_ylim(0, 115)
    ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=1)
    
    # Linha de meta (80%)
    ax.axhline(y=80, color='red', linestyle='--', linewidth=2, alpha=0.5, label='Meta: 80%')
    ax.legend(loc='upper right', fontsize=11)
    
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Gráfico de acurácia salvo em: {output_path}")

def plot_time_chart(df, output_path):
    """Gera gráfico de tempo médio por cenário."""
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Remover "Geral" para esse gráfico
    df_tempo = df[df['Cenário'] != 'Geral'].copy()
    
    # Cores gradiente
    colors = ['#66BB6A', '#FFA726', '#EF5350']
    
    # Criar barras
    bars = ax.bar(df_tempo['Cenário'], df_tempo['Tempo Médio (s)'], color=colors, 
                  edgecolor='black', linewidth=1.5)
    
    # Adicionar valores nas barras
    for bar, tempo in zip(bars, df_tempo['Tempo Médio (s)']):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width()/2., 
            height + 0.1,
            f'{tempo:.2f}s',
            ha='center', 
            va='bottom', 
            fontsize=12, 
            fontweight='bold'
        )
    
    # Configurações do gráfico
    ax.set_ylabel('Tempo Médio de Execução (segundos)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Cenário de Teste', fontsize=14, fontweight='bold')
    ax.set_title('Desempenho do Sistema - Tempo Médio por Cenário', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_ylim(0, max(df_tempo['Tempo Médio (s)']) * 1.2)
    ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=1)
    
    # Linha de média geral
    media_geral = df[df['Cenário'] == 'Geral']['Tempo Médio (s)'].values[0]
    ax.axhline(y=media_geral, color='blue', linestyle='--', linewidth=2, alpha=0.5, 
               label=f'Média Geral: {media_geral:.2f}s')
    ax.legend(loc='upper right', fontsize=11)
    
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Gráfico de tempo salvo em: {output_path}")

def plot_combined_chart(df, output_path):
    """Gera gráfico combinado (acurácia + tempo)."""
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    
    # Remover "Geral" para visualização
    df_cenarios = df[df['Cenário'] != 'Geral'].copy()
    
    # Subplot 1: Acurácia
    colors_acc = ['#4CAF50', '#FFC107', '#FF5722']
    bars1 = ax1.bar(df_cenarios['Cenário'], df_cenarios['Acurácia (%)'], 
                    color=colors_acc, edgecolor='black', linewidth=1.5)
    
    for bar, acuracia in zip(bars1, df_cenarios['Acurácia (%)']):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 2,
                f'{acuracia:.1f}%', ha='center', va='bottom', 
                fontsize=11, fontweight='bold')
    
    ax1.set_ylabel('Acurácia (%)', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Cenário', fontsize=12, fontweight='bold')
    ax1.set_title('(a) Acurácia por Cenário', fontsize=13, fontweight='bold')
    ax1.set_ylim(0, 110)
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    ax1.axhline(y=78.6, color='blue', linestyle='--', linewidth=1.5, alpha=0.5, label='Média: 78.6%')
    ax1.legend(fontsize=10)
    
    # Subplot 2: Tempo
    colors_time = ['#66BB6A', '#FFA726', '#EF5350']
    bars2 = ax2.bar(df_cenarios['Cenário'], df_cenarios['Tempo Médio (s)'], 
                    color=colors_time, edgecolor='black', linewidth=1.5)
    
    for bar, tempo in zip(bars2, df_cenarios['Tempo Médio (s)']):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                f'{tempo:.2f}s', ha='center', va='bottom', 
                fontsize=11, fontweight='bold')
    
    ax2.set_ylabel('Tempo Médio (s)', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Cenário', fontsize=12, fontweight='bold')
    ax2.set_title('(b) Tempo Médio por Cenário', fontsize=13, fontweight='bold')
    ax2.set_ylim(0, max(df_cenarios['Tempo Médio (s)']) * 1.2)
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    ax2.axhline(y=4.96, color='blue', linestyle='--', linewidth=1.5, alpha=0.5, label='Média: 4.96s')
    ax2.legend(fontsize=10)
    
    fig.suptitle('Resultados do Experimento Controlado', fontsize=16, fontweight='bold', y=0.98)
    
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Gráfico combinado salvo em: {output_path}")

def print_statistics(df):
    """Imprime estatísticas resumidas."""
    
    print("\n📊 Estatísticas do Experimento:")
    print("=" * 50)
    print(df.to_string(index=False))
    print("=" * 50)
    
    # Métricas globais
    acuracia_geral = df[df['Cenário'] == 'Geral']['Acurácia (%)'].values[0]
    tempo_geral = df[df['Cenário'] == 'Geral']['Tempo Médio (s)'].values[0]
    total_casos = df[df['Cenário'] == 'Geral']['Casos'].values[0]
    total_corretos = df[df['Cenário'] == 'Geral']['Corretos'].values[0]
    
    print(f"\n🎯 Métricas Globais:")
    print(f"   Acurácia: {acuracia_geral:.1f}% ({total_corretos}/{total_casos})")
    print(f"   Tempo Médio: {tempo_geral:.2f}s")
    print(f"   Melhor Cenário: {df.iloc[0]['Cenário'].replace(chr(10), ' ')} ({df.iloc[0]['Acurácia (%)']}%)")
    print(f"   Pior Cenário: {df.iloc[2]['Cenário'].replace(chr(10), ' ')} ({df.iloc[2]['Acurácia (%)']}%)")

def main():
    """Função principal."""
    
    print("🔧 Gerando gráficos dos resultados do experimento...")
    
    # Carregar dados
    df = load_experiment_results()
    
    # Definir caminhos de saída
    base_path = Path(__file__).parent.parent / "tcc_latex" / "figuras"
    
    # Gerar gráficos
    plot_accuracy_chart(df, base_path / "resultados_acuracia.png")
    plot_time_chart(df, base_path / "resultados_tempo.png")
    plot_combined_chart(df, base_path / "resultados_combinado.png")
    
    # Imprimir estatísticas
    print_statistics(df)
    
    print("\n✨ Concluído! 3 gráficos gerados com sucesso.")

if __name__ == "__main__":
    main()
