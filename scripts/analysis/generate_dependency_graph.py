"""
Script para gerar visualização do grafo de dependências DAX.

Este script cria uma figura ilustrativa mostrando as relações de dependência
entre colunas, tabelas e medidas em um modelo semântico Power BI.

Uso:
    python generate_dependency_graph.py
    
Saída:
    tcc_latex/figuras/grafo_dependencias.png (300 DPI)
"""

import networkx as nx
import matplotlib.pyplot as plt
from pathlib import Path

def create_dependency_graph():
    """Cria grafo de exemplo com dependências DAX realistas."""
    
    # Criar grafo direcionado
    G = nx.DiGraph()
    
    # Adicionar nós (objetos DAX)
    nodes = {
        # Colunas (base)
        "Vendas[Valor]": {"type": "column", "color": "#E3F2FD"},
        "Vendas[Quantidade]": {"type": "column", "color": "#E3F2FD"},
        "Vendas[Custo]": {"type": "column", "color": "#E3F2FD"},
        "Produtos[Categoria]": {"type": "column", "color": "#E3F2FD"},
        
        # Medidas (nível 1)
        "[Total Vendas]": {"type": "measure", "color": "#C8E6C9"},
        "[Total Custo]": {"type": "measure", "color": "#C8E6C9"},
        "[Total Quantidade]": {"type": "measure", "color": "#C8E6C9"},
        
        # Medidas (nível 2 - derivadas)
        "[Ticket Médio]": {"type": "measure", "color": "#FFF9C4"},
        "[Margem Bruta]": {"type": "measure", "color": "#FFF9C4"},
        "[Margem %]": {"type": "measure", "color": "#FFF9C4"},
        
        # Medidas (nível 3 - alto nível)
        "[ROI]": {"type": "measure", "color": "#FFCCBC"},
    }
    
    for node, attrs in nodes.items():
        G.add_node(node, **attrs)
    
    # Adicionar arestas (dependências)
    edges = [
        # Colunas → Medidas nível 1
        ("Vendas[Valor]", "[Total Vendas]"),
        ("Vendas[Custo]", "[Total Custo]"),
        ("Vendas[Quantidade]", "[Total Quantidade]"),
        
        # Medidas nível 1 → Medidas nível 2
        ("[Total Vendas]", "[Ticket Médio]"),
        ("[Total Quantidade]", "[Ticket Médio]"),
        ("[Total Vendas]", "[Margem Bruta]"),
        ("[Total Custo]", "[Margem Bruta]"),
        ("[Margem Bruta]", "[Margem %]"),
        ("[Total Vendas]", "[Margem %]"),
        
        # Medidas nível 2 → Medidas nível 3
        ("[Margem Bruta]", "[ROI]"),
        ("[Total Custo]", "[ROI]"),
    ]
    
    G.add_edges_from(edges)
    
    return G

def visualize_graph(G, output_path):
    """Gera visualização do grafo e salva como PNG."""
    
    # Configurar figura
    plt.figure(figsize=(14, 10))
    
    # Layout hierárquico
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)
    
    # Extrair cores dos nós
    node_colors = [G.nodes[node]['color'] for node in G.nodes()]
    
    # Desenhar grafo
    nx.draw_networkx_nodes(
        G, pos,
        node_color=node_colors,
        node_size=4000,
        edgecolors='black',
        linewidths=2
    )
    
    nx.draw_networkx_labels(
        G, pos,
        font_size=9,
        font_weight='bold',
        font_family='sans-serif'
    )
    
    nx.draw_networkx_edges(
        G, pos,
        edge_color='#757575',
        arrows=True,
        arrowsize=20,
        arrowstyle='->',
        width=2,
        connectionstyle='arc3,rad=0.1'
    )
    
    # Título e legenda
    plt.title("Grafo de Dependências DAX - Exemplo Real", 
              fontsize=16, fontweight='bold', pad=20)
    
    # Adicionar legenda
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#E3F2FD', edgecolor='black', label='Colunas (base)'),
        Patch(facecolor='#C8E6C9', edgecolor='black', label='Medidas (nível 1)'),
        Patch(facecolor='#FFF9C4', edgecolor='black', label='Medidas (nível 2)'),
        Patch(facecolor='#FFCCBC', edgecolor='black', label='Medidas (nível 3)')
    ]
    plt.legend(handles=legend_elements, loc='upper left', fontsize=11)
    
    plt.axis('off')
    plt.tight_layout()
    
    # Salvar com alta resolução
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Figura salva em: {output_path}")
    
    # Estatísticas do grafo
    print(f"\n📊 Estatísticas do Grafo:")
    print(f"   Nós: {G.number_of_nodes()}")
    print(f"   Arestas: {G.number_of_edges()}")
    print(f"   Colunas: {sum(1 for n in G.nodes() if G.nodes[n]['type'] == 'column')}")
    print(f"   Medidas: {sum(1 for n in G.nodes() if G.nodes[n]['type'] == 'measure')}")
    print(f"   Densidade: {nx.density(G):.3f}")

def main():
    """Função principal."""
    
    print("🔧 Gerando grafo de dependências DAX...")
    
    # Criar grafo
    G = create_dependency_graph()
    
    # Definir caminho de saída
    output_path = Path(__file__).parent.parent / "tcc_latex" / "figuras" / "grafo_dependencias.png"
    
    # Visualizar e salvar
    visualize_graph(G, output_path)
    
    print("\n✨ Concluído!")

if __name__ == "__main__":
    main()
