"""Gera grafo_dependencias_exemplo.png para o TCC."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

G = nx.DiGraph()

# Nós
coluna      = "Sales[Amount]"
medida1     = "Total Sales"
medida2     = "Sales YTD"
medida3     = "Sales Growth"
medida4     = "Avg Sales"
calc_col    = "Sales[Margin %]"

nodes = [coluna, medida1, medida2, medida3, medida4, calc_col]

# Arestas: origem → destino  (A depende de B: A → B)
edges = [
    (medida1,  coluna),     # direto
    (calc_col, coluna),     # direto
    (medida4,  coluna),     # direto
    (medida2,  medida1),    # cascata
    (medida3,  medida1),    # cascata
]

G.add_nodes_from(nodes)
G.add_edges_from(edges)

# Layout manual para ficar legível
pos = {
    coluna:   (0, 0),
    medida1:  (2, 0.8),
    calc_col: (2, 0),
    medida4:  (2, -0.8),
    medida2:  (4, 1.2),
    medida3:  (4, 0.4),
}

# Cores por categoria
color_map = {
    coluna:   "#E74C3C",   # vermelho — objeto modificado
    medida1:  "#E67E22",   # laranja — impacto direto
    calc_col: "#E67E22",
    medida4:  "#E67E22",
    medida2:  "#3498DB",   # azul — impacto em cascata
    medida3:  "#3498DB",
}
node_colors = [color_map[n] for n in G.nodes()]

# Edge colors
direct_edges   = [(medida1, coluna), (calc_col, coluna), (medida4, coluna)]
cascade_edges  = [(medida2, medida1), (medida3, medida1)]
edge_colors    = ["#E67E22" if e in direct_edges else "#3498DB" for e in G.edges()]

fig, ax = plt.subplots(figsize=(10, 5.5))
ax.set_facecolor("#F8F9FA")
fig.patch.set_facecolor("#F8F9FA")

nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=2200,
                       ax=ax, alpha=0.92)
nx.draw_networkx_labels(G, pos, font_size=8.5, font_color="white",
                        font_weight="bold", ax=ax)
nx.draw_networkx_edges(G, pos, edge_color=edge_colors, width=2.2,
                       arrows=True, arrowsize=22,
                       connectionstyle="arc3,rad=0.08", ax=ax,
                       node_size=2200)

# Anotações de tipo
type_labels = {
    coluna:   "coluna",
    medida1:  "medida",
    calc_col: "col. calculada",
    medida4:  "medida",
    medida2:  "medida",
    medida3:  "medida",
}
for node, (x, y) in pos.items():
    ax.text(x, y - 0.23, type_labels[node], ha="center", va="top",
            fontsize=7, color="#555555", style="italic")

# Legenda
legend_handles = [
    mpatches.Patch(color="#E74C3C", label="Objeto modificado"),
    mpatches.Patch(color="#E67E22", label="Impacto direto"),
    mpatches.Patch(color="#3498DB", label="Impacto em cascata"),
]
ax.legend(handles=legend_handles, loc="lower right", fontsize=9,
          framealpha=0.9)

ax.set_title("Grafo de Dependências — Renomeio de Sales[Amount]",
             fontsize=11, pad=12)
ax.axis("off")
plt.tight_layout()

out = r"C:\Users\USER\Documents\FACULDADE\TCC\tcc_latex\figuras_teste\grafo_dependencias_exemplo.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Salvo em: {out}")
