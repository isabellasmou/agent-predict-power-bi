"""
Script para gerar todas as figuras do TCC automaticamente
Autor: Isabella da Silva Moura
Data: 2026-06-14
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os

# Criar diretório se não existir
os.makedirs('tcc_latex/figuras', exist_ok=True)

# ============================================================================
# FIGURA 1: Pipeline de Arquitetura
# ============================================================================
print("🎨 Gerando pipeline_arquitetura.png...")

fig, ax = plt.subplots(figsize=(14, 3.5))
stages = ['Discovery\n(Grafo)', 'Refatoração\n(LLM)', 'Validação\n(Sintaxe)', 'Aplicação\n(MCP/pbit)']
colors = ['#E3F2FD', '#BBDEFB', '#90CAF9', '#64B5F6']

for i, (stage, color) in enumerate(zip(stages, colors)):
    rect = mpatches.FancyBboxPatch((i*3, 0), 2.5, 1.2, boxstyle="round,pad=0.1", 
                                    edgecolor='#1565C0', facecolor=color, linewidth=2.5)
    ax.add_patch(rect)
    ax.text(i*3 + 1.25, 0.6, stage, ha='center', va='center', fontsize=13, weight='bold')
    if i < len(stages) - 1:
        ax.arrow(i*3 + 2.6, 0.6, 0.3, 0, head_width=0.2, head_length=0.15, 
                 fc='#1565C0', ec='#1565C0', linewidth=2)

ax.set_xlim(-0.5, 12)
ax.set_ylim(-0.5, 2)
ax.axis('off')
plt.tight_layout()
plt.savefig('tcc_latex/figuras/pipeline_arquitetura.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print("✅ pipeline_arquitetura.png criado!")

# ============================================================================
# FIGURA 2: Resultados - Acurácia e Tempo
# ============================================================================
print("🎨 Gerando resultados_acuracia_tempo.png...")

scenarios = ['Renomeio\nde Medida', 'Renomeio\nde Tabela', 'Renomeio\nde Coluna']
accuracy = [100.0, 75.0, 71.4]
avg_time = [7.6, 2.5, 5.4]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Gráfico 1: Acurácia
colors_acc = ['#4CAF50', '#FFC107', '#FF9800']
bars = ax1.bar(scenarios, accuracy, color=colors_acc, edgecolor='black', linewidth=1.5, alpha=0.8)
ax1.set_ylabel('Acurácia (%)', fontsize=13, weight='bold')
ax1.set_ylim(0, 115)
ax1.set_title('Acurácia por Cenário de Mudança Estrutural', fontsize=14, weight='bold', pad=15)
ax1.axhline(y=78.6, color='red', linestyle='--', linewidth=2.5, label='Média Geral (78,6%)')
ax1.legend(fontsize=11)
ax1.grid(axis='y', alpha=0.3, linestyle='--')
for bar, acc in zip(bars, accuracy):
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height + 2,
             f'{acc:.1f}%', ha='center', va='bottom', fontsize=12, weight='bold')

# Gráfico 2: Tempo médio
bars2 = ax2.bar(scenarios, avg_time, color='#2196F3', edgecolor='black', linewidth=1.5, alpha=0.8)
ax2.set_ylabel('Tempo Médio (segundos)', fontsize=13, weight='bold')
ax2.set_ylim(0, 10)
ax2.set_title('Tempo Médio de Resposta por Cenário', fontsize=14, weight='bold', pad=15)
ax2.axhline(y=4.96, color='red', linestyle='--', linewidth=2.5, label='Média Geral (4,96s)')
ax2.legend(fontsize=11)
ax2.grid(axis='y', alpha=0.3, linestyle='--')
for bar, time in zip(bars2, avg_time):
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height + 0.3,
             f'{time:.1f}s', ha='center', va='bottom', fontsize=12, weight='bold')

plt.tight_layout()
plt.savefig('tcc_latex/figuras/resultados_acuracia_tempo.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print("✅ resultados_acuracia_tempo.png criado!")

# ============================================================================
# FIGURA 3: Distribuição de Tempos de Resposta
# ============================================================================
print("🎨 Gerando distribuicao_tempos.png...")

# Dados baseados no texto: 42,9% < 1s, 21,4% 1-5s, 21,4% 5-10s, 14,3% > 10s
categories = ['< 1s', '1-5s', '5-10s', '> 10s']
percentages = [42.9, 21.4, 21.4, 14.3]
colors_dist = ['#4CAF50', '#8BC34A', '#FFC107', '#FF5722']

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(categories, percentages, color=colors_dist, edgecolor='black', linewidth=1.5, alpha=0.85)
ax.set_ylabel('Proporção de Casos (%)', fontsize=13, weight='bold')
ax.set_xlabel('Faixa de Tempo de Resposta', fontsize=13, weight='bold')
ax.set_ylim(0, 50)
ax.set_title('Distribuição de Tempos de Resposta do LLM', fontsize=14, weight='bold', pad=15)
ax.grid(axis='y', alpha=0.3, linestyle='--')

for bar, pct in zip(bars, percentages):
    height = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., height + 1,
            f'{pct:.1f}%\n({int(pct*14/100)} casos)', ha='center', va='bottom', fontsize=11, weight='bold')

plt.tight_layout()
plt.savefig('tcc_latex/figuras/distribuicao_tempos.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print("✅ distribuicao_tempos.png criado!")

# ============================================================================
# FIGURA 4: Ciclo DSR
# ============================================================================
print("🎨 Gerando fluxo_dsr.png...")

fig, ax = plt.subplots(figsize=(9, 11))
stages_dsr = [
    '1. Conscientização\ndo Problema',
    '2. Sugestão de\nSolução',
    '3. Desenvolvimento\ndo Artefato',
    '4. Avaliação\nExperimental',
    '5. Conclusão'
]

for i, stage in enumerate(stages_dsr):
    y = 4.5 - i*1.0
    rect = mpatches.FancyBboxPatch((1.5, y), 6, 0.8, boxstyle="round,pad=0.08",
                                    edgecolor='#1565C0', facecolor='#E1F5FE', linewidth=2.5)
    ax.add_patch(rect)
    ax.text(4.5, y + 0.4, stage, ha='center', va='center', fontsize=12, weight='bold')
    if i < len(stages_dsr) - 1:
        ax.arrow(4.5, y - 0.05, 0, -0.12, head_width=0.4, head_length=0.06, 
                 fc='#1565C0', ec='#1565C0', linewidth=2.5)

ax.set_xlim(0, 9)
ax.set_ylim(-0.5, 5.5)
ax.axis('off')
plt.title('Ciclo da Design Science Research (DSR)', fontsize=15, weight='bold', pad=20)
plt.tight_layout()
plt.savefig('tcc_latex/figuras/fluxo_dsr.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()
print("✅ fluxo_dsr.png criado!")

# ============================================================================
# FIGURA 5: Exemplo de Grafo de Dependências (simplificado)
# ============================================================================
print("🎨 Gerando grafo_dependencias_exemplo.png...")

try:
    import networkx as nx
    
    # Criar grafo exemplo baseado no caso C1-03 (Total Sales com múltiplas referências)
    G = nx.DiGraph()
    
    # Nós
    nodes = {
        'Sales[Amount]': {'color': '#FF5722', 'size': 1500},  # Coluna alvo
        'Sales[Quantity]': {'color': '#FFC107', 'size': 1200},
        'Total Sales': {'color': '#4CAF50', 'size': 1500},  # Medida impactada
        'Avg Sales': {'color': '#2196F3', 'size': 1200},
        'Sales Margin %': {'color': '#2196F3', 'size': 1200}
    }
    
    G.add_nodes_from(nodes.keys())
    
    # Arestas (dependências)
    edges = [
        ('Sales[Amount]', 'Total Sales'),
        ('Sales[Quantity]', 'Total Sales'),
        ('Total Sales', 'Avg Sales'),
        ('Total Sales', 'Sales Margin %')
    ]
    G.add_edges_from(edges)
    
    # Layout
    fig, ax = plt.subplots(figsize=(12, 8))
    pos = nx.spring_layout(G, k=1.5, iterations=50, seed=42)
    
    # Desenhar nós
    node_colors = [nodes[node]['color'] for node in G.nodes()]
    node_sizes = [nodes[node]['size'] for node in G.nodes()]
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, 
                           edgecolors='black', linewidths=2, alpha=0.9, ax=ax)
    
    # Desenhar labels
    nx.draw_networkx_labels(G, pos, font_size=10, font_weight='bold', ax=ax)
    
    # Desenhar arestas
    nx.draw_networkx_edges(G, pos, edge_color='gray', arrows=True, arrowsize=20, 
                           width=2, arrowstyle='->', ax=ax)
    
    plt.title('Grafo de Dependências - Exemplo: Renomeio Sales[Amount]', 
              fontsize=14, weight='bold', pad=20)
    ax.axis('off')
    plt.tight_layout()
    plt.savefig('tcc_latex/figuras/grafo_dependencias_exemplo.png', dpi=300, 
                bbox_inches='tight', facecolor='white')
    plt.close()
    print("✅ grafo_dependencias_exemplo.png criado!")
    
except ImportError:
    print("⚠️  NetworkX não instalado. Pulando grafo de dependências.")
    print("    Instale com: pip install networkx")

# ============================================================================
print("\n" + "="*60)
print("🎉 TODAS AS FIGURAS FORAM GERADAS COM SUCESSO!")
print("="*60)
print("\n📁 Localização: tcc_latex/figuras/")
print("\n📋 Figuras criadas:")
print("   1. pipeline_arquitetura.png")
print("   2. resultados_acuracia_tempo.png")
print("   3. distribuicao_tempos.png")
print("   4. fluxo_dsr.png")
print("   5. grafo_dependencias_exemplo.png (se NetworkX instalado)")
print("\n⚠️  FALTA APENAS:")
print("   - interface_streamlit.png (captura manual - execute 'streamlit run app.py')")
print("\n✅ Compile o LaTeX para verificar se as figuras aparecem corretamente!")
