"""
Script para gerar diagrama da arquitetura do PBI Refactor Agent.

Cria uma visualização em camadas mostrando a estrutura completa do sistema.

Uso:
    python scripts/figures/generate_architecture_diagram.py
    
Saída:
    tcc_latex/figuras/arquitetura_sistema.png (300 DPI)
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

# Criar diretório se não existir
Path('tcc_latex/figuras').mkdir(parents=True, exist_ok=True)

print("🎨 Gerando diagrama de arquitetura do sistema...")

# ============================================================================
# Configuração da figura
# ============================================================================
fig, ax = plt.subplots(figsize=(16, 12))
ax.set_xlim(0, 16)
ax.set_ylim(0, 12)
ax.axis('off')

# ============================================================================
# Definição das camadas e componentes
# ============================================================================

# Camada 1: Interface (Streamlit UI)
layer1_y = 10.5
ax.text(8, layer1_y + 0.8, '📱 CAMADA DE INTERFACE', 
        ha='center', fontsize=14, weight='bold', 
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#E8EAF6', edgecolor='#3F51B5', linewidth=2))

streamlit_box = mpatches.FancyBboxPatch((1, layer1_y - 0.5), 14, 0.8, 
                                        boxstyle="round,pad=0.1",
                                        edgecolor='#3F51B5', facecolor='#C5CAE9', linewidth=2)
ax.add_patch(streamlit_box)
ax.text(8, layer1_y, 'app.py (Streamlit)', ha='center', va='center', fontsize=11, weight='bold')
ax.text(8, layer1_y - 0.3, '6 Abas: Conectar | Explorar | Impacto | Refatorar | Diagnóstico | Experimento', 
        ha='center', va='center', fontsize=9, style='italic', color='#1A237E')

# Camada 2: Orquestração (Agent)
layer2_y = 8.5
ax.text(8, layer2_y + 0.8, '🎯 CAMADA DE ORQUESTRAÇÃO', 
        ha='center', fontsize=14, weight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#E0F2F1', edgecolor='#00796B', linewidth=2))

agent_box = mpatches.FancyBboxPatch((3, layer2_y - 0.4), 10, 0.7,
                                    boxstyle="round,pad=0.1",
                                    edgecolor='#00796B', facecolor='#B2DFDB', linewidth=2)
ax.add_patch(agent_box)
ax.text(8, layer2_y, 'RefactorAgent', ha='center', va='center', fontsize=11, weight='bold')
ax.text(8, layer2_y - 0.25, 'Coordena fluxo: Discovery → Refactor → Validation → Application',
        ha='center', va='center', fontsize=8, style='italic', color='#004D40')

# Setas UI → Agent
ax.annotate('', xy=(8, layer2_y + 0.3), xytext=(8, layer1_y - 0.5),
            arrowprops=dict(arrowstyle='->', lw=2.5, color='#455A64'))

# Camada 3: Módulos Core (Discovery, Refactor, Validation)
layer3_y = 5.8

ax.text(8, layer3_y + 1.2, '⚙️ CAMADA DE MÓDULOS CORE', 
        ha='center', fontsize=14, weight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFF3E0', edgecolor='#F57C00', linewidth=2))

# Módulo Discovery
discovery_x = 2
discovery_box = mpatches.FancyBboxPatch((discovery_x - 1.2, layer3_y - 1), 3.2, 1.8,
                                        boxstyle="round,pad=0.1",
                                        edgecolor='#F57C00', facecolor='#FFE0B2', linewidth=2)
ax.add_patch(discovery_box)
ax.text(discovery_x + 0.4, layer3_y + 0.5, '🔍 DISCOVERY', ha='center', fontsize=11, weight='bold', color='#E65100')
discovery_items = [
    'DependencyGraph',
    'ImpactAnalyzer',
    'ModelHealthAnalyzer',
    'RiskAnalyzer',
    'DuplicateDetector',
    'ProductionValidator',
]
for i, item in enumerate(discovery_items):
    ax.text(discovery_x + 0.4, layer3_y + 0.1 - i*0.27, f'• {item}',
            ha='center', fontsize=8, color='#424242')

# Módulo Refactor
refactor_x = 8
refactor_box = mpatches.FancyBboxPatch((refactor_x - 1.6, layer3_y - 1), 3.2, 1.8,
                                       boxstyle="round,pad=0.1",
                                       edgecolor='#F57C00', facecolor='#FFE0B2', linewidth=2)
ax.add_patch(refactor_box)
ax.text(refactor_x, layer3_y + 0.5, '🔧 REFACTOR', ha='center', fontsize=11, weight='bold', color='#E65100')
refactor_items = [
    'DAXRefactor',
    'PromptEngine',
    'LLMClient',
    'AutoDocumentor',
]
for i, item in enumerate(refactor_items):
    ax.text(refactor_x, layer3_y + 0.1 - i*0.32, f'• {item}',
            ha='center', fontsize=8, color='#424242')

# Módulo Validation
validation_x = 14
validation_box = mpatches.FancyBboxPatch((validation_x - 1.6, layer3_y - 1), 3.2, 1.8,
                                         boxstyle="round,pad=0.1",
                                         edgecolor='#F57C00', facecolor='#FFE0B2', linewidth=2)
ax.add_patch(validation_box)
ax.text(validation_x, layer3_y + 0.5, '✅ VALIDATION', ha='center', fontsize=11, weight='bold', color='#E65100')
validation_items = [
    'DAXValidator',
    'SyntaxValidator',
    'EquivalenceTester',
    'PerformanceAnalyzer',
    'AntiPatternDetector',
]
for i, item in enumerate(validation_items):
    ax.text(validation_x, layer3_y + 0.1 - i*0.32, f'• {item}',
            ha='center', fontsize=8, color='#424242')

# Setas Agent → Módulos
ax.annotate('', xy=(discovery_x + 0.4, layer3_y + 0.8), xytext=(6, layer2_y - 0.4),
            arrowprops=dict(arrowstyle='->', lw=2, color='#455A64'))
ax.annotate('', xy=(refactor_x, layer3_y + 0.8), xytext=(8, layer2_y - 0.4),
            arrowprops=dict(arrowstyle='->', lw=2, color='#455A64'))
ax.annotate('', xy=(validation_x, layer3_y + 0.8), xytext=(10, layer2_y - 0.4),
            arrowprops=dict(arrowstyle='->', lw=2, color='#455A64'))

# Camada 4: Infraestrutura (LLM Providers, MCP, Utils)
layer4_y = 2.2

ax.text(8, layer4_y + 1.2, '🛠️ CAMADA DE INFRAESTRUTURA', 
        ha='center', fontsize=14, weight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#F3E5F5', edgecolor='#7B1FA2', linewidth=2))

# LLM Providers
llm_x = 3
llm_box = mpatches.FancyBboxPatch((llm_x - 1.8, layer4_y - 0.8), 3.6, 1.5,
                                  boxstyle="round,pad=0.1",
                                  edgecolor='#7B1FA2', facecolor='#E1BEE7', linewidth=2)
ax.add_patch(llm_box)
ax.text(llm_x, layer4_y + 0.4, '🤖 LLM CLIENTS', ha='center', fontsize=10, weight='bold', color='#4A148C')
llm_providers = ['Groq (Llama 3.3)', 'OpenAI (GPT-4o)', 'Google (Gemini 2.5)', 'Anthropic (Claude 3.5)']
for i, provider in enumerate(llm_providers):
    ax.text(llm_x, layer4_y - 0.1 - i*0.28, f'• {provider}',
            ha='center', fontsize=7, color='#424242')

# MCP Client
mcp_x = 8
mcp_box = mpatches.FancyBboxPatch((mcp_x - 1.5, layer4_y - 0.8), 3, 1.5,
                                  boxstyle="round,pad=0.1",
                                  edgecolor='#7B1FA2', facecolor='#E1BEE7', linewidth=2)
ax.add_patch(mcp_box)
ax.text(mcp_x, layer4_y + 0.4, '🔌 MCP CLIENT', ha='center', fontsize=10, weight='bold', color='#4A148C')
mcp_items = ['Conexão com .pbit', 'Extração de schema', 'Aplicação transacional', 'Rollback automático']
for i, item in enumerate(mcp_items):
    ax.text(mcp_x, layer4_y - 0.1 - i*0.28, f'• {item}',
            ha='center', fontsize=7, color='#424242')

# Utils
utils_x = 13
utils_box = mpatches.FancyBboxPatch((utils_x - 1.5, layer4_y - 0.8), 3, 1.5,
                                    boxstyle="round,pad=0.1",
                                    edgecolor='#7B1FA2', facecolor='#E1BEE7', linewidth=2)
ax.add_patch(utils_box)
ax.text(utils_x, layer4_y + 0.4, '🧰 UTILS', ha='center', fontsize=10, weight='bold', color='#4A148C')
utils_items = ['pbix_extractor', 'logging (structlog)', 'reporting', 'models (Pydantic)']
for i, item in enumerate(utils_items):
    ax.text(utils_x, layer4_y - 0.1 - i*0.28, f'• {item}',
            ha='center', fontsize=7, color='#424242')

# Setas Módulos → Infraestrutura
ax.annotate('', xy=(llm_x, layer4_y + 0.7), xytext=(refactor_x - 0.5, layer3_y - 1),
            arrowprops=dict(arrowstyle='->', lw=1.5, color='#455A64', linestyle='dashed'))
ax.annotate('', xy=(mcp_x, layer4_y + 0.7), xytext=(discovery_x + 1.5, layer3_y - 1),
            arrowprops=dict(arrowstyle='->', lw=1.5, color='#455A64', linestyle='dashed'))
ax.annotate('', xy=(utils_x, layer4_y + 0.7), xytext=(validation_x - 0.5, layer3_y - 1),
            arrowprops=dict(arrowstyle='->', lw=1.5, color='#455A64', linestyle='dashed'))

# Camada 5: Dados (Power BI Model)
layer5_y = 0.5
model_box = mpatches.FancyBboxPatch((5, layer5_y - 0.3), 6, 0.6,
                                    boxstyle="round,pad=0.1",
                                    edgecolor='#D32F2F', facecolor='#FFCDD2', linewidth=2)
ax.add_patch(model_box)
ax.text(8, layer5_y, '📊 Power BI Model (.pbit/.pbix)', 
        ha='center', va='center', fontsize=11, weight='bold', color='#B71C1C')

# Seta Infraestrutura → Modelo
ax.annotate('', xy=(8, layer5_y + 0.3), xytext=(8, layer4_y - 0.8),
            arrowprops=dict(arrowstyle='<->', lw=2.5, color='#D32F2F'))

# ============================================================================
# Legenda
# ============================================================================
legend_y = 11.5
legend_items = [
    ('Fluxo principal', '#455A64', '-'),
    ('Dependência', '#455A64', '--'),
    ('Acesso a dados', '#D32F2F', '-'),
]

legend_x_start = 0.5
for i, (label, color, style) in enumerate(legend_items):
    x_pos = legend_x_start + i * 4
    ax.plot([x_pos, x_pos + 0.8], [legend_y, legend_y], 
            color=color, linewidth=2, linestyle=style)
    ax.text(x_pos + 1, legend_y, label, va='center', fontsize=9)

# Título
plt.title('Arquitetura do PBI Refactor Agent\nSistema Multi-Camadas para Refatoração de Modelos Power BI', 
          fontsize=16, weight='bold', pad=20, loc='center')

# Rodapé
ax.text(8, 0.1, 'TCC - Isabella da Silva Moura | FAETERJ 2026', 
        ha='center', fontsize=9, style='italic', color='#616161')

# Salvar
plt.tight_layout()
plt.savefig('tcc_latex/figuras/arquitetura_sistema.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close()

print("✅ Diagrama criado: tcc_latex/figuras/arquitetura_sistema.png")
print("📐 Dimensões: 16x12 polegadas @ 300 DPI")
print("🎨 Pronto para apresentação!")