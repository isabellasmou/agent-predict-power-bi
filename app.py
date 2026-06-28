import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pbi_refactor_agent import RefactorAgent
from pbi_refactor_agent.models import ChangeType, ProposedChange, SyntaxValidation
from pbi_refactor_agent.config import LLMProvider, get_settings
from pbi_refactor_agent.discovery import ImpactAnalyzer
from pbi_refactor_agent.refactor import DAXRefactor
from pbi_refactor_agent.validation import SyntaxValidator, AntiPatternDetector
from pbi_refactor_agent.utils.reporting import ReportGenerator
from pbi_refactor_agent.utils.pbix_extractor import (
    extract_model,
    extract_raw_schema_tables,
    load_model_into_graph,
    generate_markdown_report,
    save_refactored_pbit,
    ExtractionError,
    ModelMetadata,
    CATEGORY_LABELS_PT,
)

st.set_page_config(
    page_title="PBI Refactor Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS externo
_css_path = Path(__file__).parent / "src" / "pbi_refactor_agent" / "static" / "style.css"
if _css_path.exists():
    st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# Cache helpers
@st.cache_data(show_spinner=False)
def cached_extract_model(file_path: str):
    """Cache extração de metadados (evita re-parse ao interagir)."""
    return extract_model(file_path)


@st.cache_resource
def cached_settings():
    """Cache de settings (lê .env uma vez)."""
    return get_settings()


@st.cache_resource
def cached_dax_refactor():
    """Cache do DAXRefactor client."""
    return DAXRefactor(settings=cached_settings())


# Plotly theme
PLOTLY_COLORS = ["#7C3AED", "#A78BFA", "#C4B5FD", "#34D399", "#FBBF24", "#F87171", "#60A5FA"]
PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, -apple-system, system-ui, sans-serif", color="#CBD5E1", size=12),
    margin=dict(t=40, b=20, l=40, r=20),
    xaxis=dict(gridcolor="rgba(55,65,81,0.2)", gridwidth=1, zeroline=False),
    yaxis=dict(gridcolor="rgba(55,65,81,0.2)", gridwidth=1, zeroline=False),
    hoverlabel=dict(bgcolor="#1E2235", bordercolor="rgba(124,58,237,0.3)", font_size=12),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)"),
)


if "agent" not in st.session_state:
    st.session_state.agent = None
if "connected" not in st.session_state:
    st.session_state.connected = False
if "model_summary" not in st.session_state:
    st.session_state.model_summary = None
if "model_metadata" not in st.session_state:
    st.session_state.model_metadata = None
if "dependency_graph" not in st.session_state:
    st.session_state.dependency_graph = None
if "impact_results" not in st.session_state:
    st.session_state.impact_results = []
if "refactor_history" not in st.session_state:
    st.session_state.refactor_history = []

st.markdown(
    '<div class="hero">'
    '<div class="hero-badge">TCC — FAETERJ 2026</div>'
    '<h1>PBI Refactor <span class="accent">Agent</span></h1>'
    '<p class="hero-sub">'
    'Refatore modelos Power BI automaticamente com IA. '
    'Detecte impactos, corrija DAX e valide mudanças antes da produção.'
    '</p>'
    '</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    # Branding
    st.markdown(
        '<div class="sb-brand">'
        '<div class="sb-logo">⚡</div>'
        '<div><div class="sb-name">PBI Refactor Agent</div>'
        '<div class="sb-ver">v1.0 — TCC 2026</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # LLM Provider
    st.markdown('<div class="sb-section">Provedor LLM</div>', unsafe_allow_html=True)
    llm_provider = st.selectbox(
        "Provedor",
        options=["groq", "openai", "google", "anthropic"],
        format_func=lambda x: {
            "groq": "Groq — Llama 3.3 70B",
            "openai": "OpenAI — GPT-4o",
            "google": "Google — Gemini 2.5 Flash",
            "anthropic": "Anthropic — Claude 3.5",
        }[x],
        label_visibility="collapsed",
    )

    model_options = {
        "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "openai": ["gpt-4o", "gpt-4o-mini"],
        "google": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-flash"],
        "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    }
    llm_model = st.selectbox("Modelo", options=model_options[llm_provider], label_visibility="collapsed")

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

    # API Status chips
    st.markdown('<div class="sb-section">API Keys</div>', unsafe_allow_html=True)
    _settings = cached_settings()
    _key_status = {
        "GROQ": bool(_settings.groq_api_key),
        "OPENAI": bool(_settings.openai_api_key),
        "GOOGLE": bool(_settings.google_api_key),
        "ANTHROPIC": bool(_settings.anthropic_api_key),
    }
    chips_html = '<div class="sb-chips">'
    for provider_name, has_key in _key_status.items():
        cls = "on" if has_key else "off"
        chips_html += (
            f'<span class="sb-chip {cls}">'
            f'<span class="sb-chip-dot"></span>{provider_name}'
            '</span>'
        )
    chips_html += '</div>'
    st.markdown(chips_html, unsafe_allow_html=True)

    if not any(_key_status.values()):
        st.caption("Configure ao menos uma chave no `.env`")

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

    # Connection status
    st.markdown('<div class="sb-section">Modelo</div>', unsafe_allow_html=True)
    if st.session_state.connected and st.session_state.model_summary:
        summary = st.session_state.model_summary
        st.markdown(
            '<div class="sb-status">'
            '<span class="sb-dot online"></span>'
            '<div>'
            f'<div class="sb-status-text">{summary.get("file_name", "Conectado")}</div>'
            f'<div class="sb-status-sub">{summary.get("business_tables", 0)} tabelas — {summary.get("total_measures", 0)} medidas</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="sb-status">'
            '<span class="sb-dot offline"></span>'
            '<div><div class="sb-status-text">Nenhum modelo</div>'
            '<div class="sb-status-sub">Faça upload de um .pbit</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

    # Advanced options
    with st.expander("Opções avançadas"):
        validate_syntax = st.checkbox("Validar sintaxe", value=True)
        validate_equivalence = st.checkbox("Testar equivalência", value=True)
        auto_apply = st.checkbox(
            "Aplicar automaticamente",
            value=False,
            help="Aplica mudanças sem confirmação",
        )

    # Help
    st.markdown(
        '<div class="sb-help">'
        '<strong>1.</strong> Upload .pbit → '
        '<strong>2.</strong> Analise impacto → '
        '<strong>3.</strong> Refatore com IA → '
        '<strong>4.</strong> Aplique com rollback'
        '</div>',
        unsafe_allow_html=True,
    )

tab_home, tab_connect, tab_explore, tab_impact, tab_refactor, tab_history = st.tabs(
    ["Visão Geral", "Conectar", "Explorar", "Impacto", "Refatorar", "Histórico"]
)

with tab_home:
    _p1 = "active" if st.session_state.connected else ""
    _p2 = "active" if st.session_state.connected else ""
    _p3 = "active" if st.session_state.impact_results else ""
    _p4 = "active" if st.session_state.refactor_history else ""
    _p5 = "active" if any(r.get("applied") for r in st.session_state.refactor_history) else ""
    st.markdown(
        '<div class="pipeline-compact">'
        f'<div class="pc-step {_p1}"><span class="pc-dot"></span>Upload</div>'
        '<span class="pc-arrow">→</span>'
        f'<div class="pc-step {_p2}"><span class="pc-dot"></span>Descoberta</div>'
        '<span class="pc-arrow">→</span>'
        f'<div class="pc-step {_p3}"><span class="pc-dot"></span>Impacto</div>'
        '<span class="pc-arrow">→</span>'
        f'<div class="pc-step {_p4}"><span class="pc-dot"></span>Refatoração</div>'
        '<span class="pc-arrow">→</span>'
        f'<div class="pc-step {_p5}"><span class="pc-dot"></span>Aplicação</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    fc1, fc2, fc3 = st.columns(3, gap="large")
    with fc1:
        st.markdown(
            '<div class="feat-card">'
            '<div class="feat-icon">🔍</div>'
            '<div class="feat-title">Descobrir</div>'
            '<p class="feat-desc">Mapeia tabelas, colunas, medidas e relacionamentos. '
            'Constrói o grafo de dependências do modelo.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    with fc2:
        st.markdown(
            '<div class="feat-card">'
            '<div class="feat-icon">🤖</div>'
            '<div class="feat-title">Refatorar</div>'
            '<p class="feat-desc">LLM reescreve expressões DAX impactadas automaticamente. '
            'Suporta Groq, OpenAI e Anthropic.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    with fc3:
        st.markdown(
            '<div class="feat-card">'
            '<div class="feat-icon">✅</div>'
            '<div class="feat-title">Validar</div>'
            '<p class="feat-desc">Detecta erros de sintaxe, anti-patterns e problemas '
            'antes de publicar em produção.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    if st.session_state.connected and st.session_state.model_summary:
        summary = st.session_state.model_summary
        st.markdown(
            '<p class="section-label" style="margin-top:1.5rem;">Modelo conectado</p>',
            unsafe_allow_html=True,
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f'<div class="kpi-card kpi-purple"><p class="kpi-value">{summary.get("business_tables", 0)}</p><p class="kpi-label">Tabelas</p></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="kpi-card kpi-blue"><p class="kpi-value">{summary.get("total_measures", 0)}</p><p class="kpi-label">Medidas</p></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="kpi-card kpi-green"><p class="kpi-value">{summary.get("total_relationships", 0)}</p><p class="kpi-label">Relacionamentos</p></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="kpi-card kpi-amber"><p class="kpi-value">{len(st.session_state.impact_results)}</p><p class="kpi-label">Análises</p></div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="onboard-card">'
            '<h4>Como começar</h4>'
            '<table>'
            '<tr><td>1.</td><td>Vá na aba <strong>Conectar Modelo</strong> e faça upload de um <code>.pbit</code></td></tr>'
            '<tr><td>2.</td><td>Explore o modelo na aba <strong>Explorar Modelo</strong></td></tr>'
            '<tr><td>3.</td><td>Defina uma mudança na aba <strong>Análise de Impacto</strong></td></tr>'
            '<tr><td>4.</td><td>Clique em <strong>Refatorar</strong> — a IA corrige as expressões DAX</td></tr>'
            '</table>'
            '<p class="tip"><strong>Dica:</strong> Sem <code>.pbit</code>? Use a aba <strong>Refatoração Rápida</strong>.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    if st.session_state.refactor_history:
        st.markdown(
            '<p class="section-label" style="margin-top:1.5rem;">Atividade recente</p>',
            unsafe_allow_html=True,
        )
        rows_html = ""
        for activity in st.session_state.refactor_history[-5:][::-1]:
            rows_html += (
                '<div class="activity-row">'
                f'<span class="ar-change">{activity["change"]}</span>'
                '<span class="ar-meta">'
                f'<span class="ar-stat">{activity["successes"]}/{activity["impacts"]}</span>'
                f'<span>{activity["time"]:.1f}s</span>'
                f'<span>{activity["timestamp"]}</span>'
                '</span>'
                '</div>'
            )
        st.markdown(rows_html, unsafe_allow_html=True)

with tab_connect:
    st.markdown('<p class="section-label">Conectar ao modelo Power BI</p>', unsafe_allow_html=True)

    connection_method = st.radio(
        "Método de conexão",
        options=["upload", "path"],
        format_func=lambda x: {
            "upload": "Upload de arquivo .pbit",
            "path": "Caminho local (.pbit)",
        }[x],
        horizontal=True,
    )

    def _connect_model(file_path_str: str):
        """Extrai metadados e popula o grafo de dependências."""
        try:
            with st.status("Conectando ao modelo...", expanded=True) as status:
                st.write("Extraindo metadados do .pbit...")
                metadata = cached_extract_model(file_path_str)
                st.write("Construindo grafo de dependências...")
                graph = load_model_into_graph(metadata)
                st.session_state.model_metadata = metadata
                st.session_state.dependency_graph = graph
                st.session_state.connected = True
                st.session_state.model_summary = metadata.summary
                status.update(
                    label=(
                        f"Conectado — {metadata.summary['business_tables']} tabelas, "
                        f"{metadata.summary['total_measures']} medidas"
                    ),
                    state="complete",
                    expanded=False,
                )
            st.toast("Modelo conectado com sucesso!", icon="✅")
        except ExtractionError as e:
            st.error(f"Erro na extração: {e}")
        except Exception as e:
            st.error(f"Erro inesperado: {e}")

    if connection_method == "upload":
        uploaded_file = st.file_uploader(
            "Selecione um arquivo .pbit",
            type=["pbit"],
        )

        if uploaded_file:
            temp_path = Path("data") / uploaded_file.name
            temp_path.parent.mkdir(exist_ok=True)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            st.markdown(
                f'<span class="badge-success">Arquivo carregado: {uploaded_file.name}</span>',
                unsafe_allow_html=True,
            )

            if st.button("Conectar", key="connect_upload"):
                _connect_model(str(temp_path))

    else:
        model_path = st.text_input(
            "Caminho do modelo",
            value="",
            help="Caminho para arquivo .pbit",
            placeholder="ex: data/meu_modelo.pbit",
        )

        if st.button("Conectar", key="connect_path"):
            if Path(model_path).exists():
                _connect_model(model_path)
            else:
                st.error(f"Arquivo não encontrado: {model_path}")

    if st.session_state.connected and st.session_state.model_summary:
        st.markdown('<p class="section-label" style="margin-top:1.5rem;">Modelo conectado</p>', unsafe_allow_html=True)
        summary = st.session_state.model_summary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tabelas", summary["business_tables"])
        c2.metric("Medidas", summary["total_measures"])
        c3.metric("Colunas", summary["total_columns"])
        c4.metric("Relacionamentos", summary["total_relationships"])

        st.markdown(
            '<div class="alert-success"><strong>Extração completa.</strong> '
            'Todas as tabelas, colunas, medidas (com DAX) e relacionamentos foram extraídos.</div>',
            unsafe_allow_html=True,
        )

with tab_explore:
    st.markdown('<p class="section-label">Explorar modelo</p>', unsafe_allow_html=True)

    if not st.session_state.connected or not st.session_state.model_metadata:
        st.info("Conecte um modelo antes de explorar.")
    else:
        from typing import cast
        meta = cast(ModelMetadata, st.session_state.model_metadata)
        business = meta.business_tables

        explore_tabs = st.tabs(["Tabelas", "Medidas e DAX", "Relacionamentos", "Documentação"])

        # Tabelas
        with explore_tabs[0]:
            st.markdown(f"**{len(business)}** tabelas de negócio encontradas")

            for table in business:
                visible_cols = [c for c in table.columns if not c.is_hidden]
                visible_measures = [m for m in table.measures if not m.is_hidden]
                label = f"{table.name}  ({len(visible_cols)} colunas, {len(visible_measures)} medidas)"
                with st.expander(label):
                    if visible_cols:
                        col_data = []
                        for c in visible_cols:
                            col_data.append({
                                "Coluna": c.name,
                                "Tipo": c.data_type,
                                "Categoria": CATEGORY_LABELS_PT.get(c.category, c.category),
                            })
                        st.dataframe(
                            pd.DataFrame(col_data),
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.caption("Nenhuma coluna visível extraída.")

                    if visible_measures:
                        st.markdown("**Medidas:**")
                        for m in visible_measures:
                            st.markdown(f"- `{m.name}` ({CATEGORY_LABELS_PT.get(m.category, m.category)})")
                    else:
                        st.caption("Nenhuma medida encontrada nesta tabela.")

        # Medidas e DAX
        with explore_tabs[1]:
            all_measures = []
            for table in business:
                for m in table.measures:
                    if not m.is_hidden:
                        all_measures.append((table.name, m))

            if not all_measures:
                st.info("Nenhuma medida encontrada. Para extração completa de DAX, use um arquivo .pbit.")
            else:
                st.markdown(f"**{len(all_measures)}** medidas encontradas")

                by_cat = {}
                for tname, m in all_measures:
                    by_cat.setdefault(m.category, []).append((tname, m))

                cat_order = [
                    "revenue", "cost", "margin", "percentage", "ratio",
                    "temporal", "calendar_intelligence", "aggregation",
                    "filtering", "other",
                ]
                for cat in cat_order:
                    if cat not in by_cat:
                        continue
                    label = CATEGORY_LABELS_PT.get(cat, cat)
                    st.markdown(f'<p class="section-label" style="margin-top:1.25rem;">{label}</p>', unsafe_allow_html=True)
                    for tname, m in by_cat[cat]:
                        cplx_map = {"simple": "simples", "medium": "média", "complex": "complexa"}
                        cplx_badge = {"simple": "badge-success", "medium": "badge-warning", "complex": "badge-error"}
                        title = f"{m.name}  ({tname}) — {cplx_map.get(m.complexity, m.complexity)}"
                        with st.expander(title):
                            if m.formatted_expression:
                                st.code(m.formatted_expression, language="dax")
                            elif m.expression:
                                st.code(m.expression, language="dax")
                            else:
                                st.caption("Expressão DAX não disponível")
                            if m.format_string:
                                st.caption(f"Formato: {m.format_string}")
                            if m.display_folder:
                                st.caption(f"Pasta: {m.display_folder}")

                if all_measures:
                    complexity_counts = {"simples": 0, "media": 0, "complexa": 0}
                    for _, m in all_measures:
                        label = {"simple": "simples", "medium": "media", "complex": "complexa"}.get(m.complexity, "simples")
                        complexity_counts[label] += 1

                    fig = go.Figure(data=[go.Pie(
                        labels=list(complexity_counts.keys()),
                        values=list(complexity_counts.values()),
                        hole=0.4,
                        marker_colors=["#34D399", "#FBBF24", "#F87171"],
                    )])
                    fig.update_layout(PLOTLY_LAYOUT)
                    fig.update_layout(title="Complexidade das medidas", height=350)
                    st.plotly_chart(fig, width="stretch")

        # Relacionamentos
        with explore_tabs[2]:
            if not meta.relationships:
                st.info("Nenhum relacionamento extraído. Para extração completa, use .pbit.")
            else:
                st.markdown(f"**{len(meta.relationships)}** relacionamentos")

                show_technical = st.checkbox("Mostrar tabelas técnicas", value=False, key="show_tech_rels")
                rel_data = []
                for r in meta.relationships:
                    if not show_technical and (r.to_table.startswith("LocalDateTable_") or r.to_table.startswith("DateTableTemplate")):
                        continue
                    rel_data.append({
                        "De": f"{r.from_table}.{r.from_column}",
                        "Para": f"{r.to_table}.{r.to_column}" if show_technical else r.to_table,
                        "Cardinalidade": r.cardinality,
                        "Direção": r.cross_filtering,
                        "Ativo": r.is_active,
                    })
                st.dataframe(
                    pd.DataFrame(rel_data),
                    hide_index=True,
                    width="stretch",
                )

                tables_in_rels = set()
                for r in meta.relationships:
                    tables_in_rels.add(r.from_table)
                    tables_in_rels.add(r.to_table)

                tables_list = sorted(
                    t for t in tables_in_rels
                    if not t.startswith("LocalDateTable_") and not t.startswith("DateTableTemplate")
                )
                if not tables_list:
                    tables_list = sorted(tables_in_rels)
                table_idx = {t: i for i, t in enumerate(tables_list)}

                import math
                n = len(tables_list)
                if n > 0:
                    node_x = [math.cos(2 * math.pi * i / n) for i in range(n)]
                    node_y = [math.sin(2 * math.pi * i / n) for i in range(n)]

                    edge_x, edge_y = [], []
                    for r in meta.relationships:
                        fi, ti = table_idx.get(r.from_table), table_idx.get(r.to_table)
                        if fi is not None and ti is not None:
                            edge_x += [node_x[fi], node_x[ti], None]
                            edge_y += [node_y[fi], node_y[ti], None]

                    table_map = {t.name: t for t in meta.tables}
                    node_sizes = []
                    node_colors = []
                    hover_texts = []
                    for tname in tables_list:
                        t = table_map.get(tname)
                        n_cols = len(t.columns) if t else 0
                        n_meas = len(t.measures) if t else 0
                        node_sizes.append(max(22, n_meas * 5 + 16))
                        is_fact = n_meas >= 1 if t else False
                        node_colors.append("#7C3AED" if is_fact else "#34D399")
                        hover_texts.append(f"<b>{tname}</b><br>{n_cols} colunas — {n_meas} medidas")

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=edge_x, y=edge_y, mode="lines",
                        line=dict(width=1.5, color="rgba(124,58,237,0.25)"),
                        hoverinfo="none",
                    ))
                    fig.add_trace(go.Scatter(
                        x=node_x, y=node_y, mode="markers+text",
                        marker=dict(
                            size=node_sizes,
                            color=node_colors,
                            line=dict(width=1.5, color="#1E2235"),
                        ),
                        text=tables_list,
                        textposition="top center",
                        textfont=dict(size=10, color="#CBD5E1"),
                        hoverinfo="text",
                        hovertext=hover_texts,
                    ))
                    fig.add_trace(go.Scatter(
                        x=[None], y=[None], mode="markers",
                        marker=dict(size=10, color="#7C3AED"),
                        name="Fato (com medidas)",
                    ))
                    fig.add_trace(go.Scatter(
                        x=[None], y=[None], mode="markers",
                        marker=dict(size=10, color="#34D399"),
                        name="Dimensão",
                    ))
                    layout_filtered = {k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis", "margin")}
                    fig.update_layout(layout_filtered)
                    fig.update_layout(
                        title="Grafo de relacionamentos",
                        showlegend=True,
                        height=520,
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        margin=dict(l=20, r=20, t=50, b=20),
                    )
                    st.plotly_chart(fig, width="stretch")

        with explore_tabs[3]:
            st.markdown("Documentação completa do modelo em Markdown")
            md_report = generate_markdown_report(meta)
            st.download_button(
                "Download Markdown",
                data=md_report,
                file_name=f"{meta.file_name}_documentacao.md",
                mime="text/markdown",
            )
            with st.expander("Visualizar Markdown"):
                st.markdown(md_report)

# Mapeamento de tipos legíveis
OBJECT_TYPE_LABELS = {
    "measure": "Medida DAX",
    "calculated_column": "Coluna Calculada",
    "column": "Coluna",
    "table": "Tabela",
    "relationship": "Relacionamento",
    "hierarchy": "Hierarquia",
    "calculation_group": "Grupo de Cálculo",
    "calculation_item": "Item de Cálculo",
    "partition": "Partição",
}
 
 
def _label_object_type(object_type) -> str:
    """Converte ObjectType enum ou string para label legível."""
    raw = str(object_type).replace("ObjectType.", "").lower()
    return OBJECT_TYPE_LABELS.get(raw, raw.replace("_", " ").title())
 
 
def _truncate(text: str | None, max_len: int = 120) -> str:
    """Trunca texto longo para exibição na tabela."""
    if not text:
        return "—"
    text = text.strip().replace("\n", " ")
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text                

with tab_impact:
    st.markdown('<p class="section-label">Análise de impacto</p>', unsafe_allow_html=True)
 
    if not st.session_state.connected:
        st.warning("Conecte um modelo antes de realizar análise de impacto.")
    else:
        meta: ModelMetadata | None = st.session_state.model_metadata
        graph = st.session_state.dependency_graph
        
        if not meta:
            st.error("Metadados do modelo não disponíveis. Reconecte o modelo.")
            st.stop()
 
        table_names = [t.name for t in meta.business_tables] if meta else ["Sales"]
 
        st.markdown("**Definir mudança**")
        c1, c2 = st.columns([1, 2])
 
        with c1:
            change_type = st.selectbox(
                "Tipo de mudança",
                options=[
                    "rename_column",
                    "rename_table",
                    "rename_measure",
                    "delete_column",
                ],
                format_func=lambda x: {
                    "rename_column": "Renomear coluna",
                    "rename_table": "Renomear tabela",
                    "rename_measure": "Renomear medida",
                    "delete_column": "Deletar coluna",
                }[x],
            )
 
        with c2:
            if change_type in ["rename_column", "delete_column"]:
                ca, cb = st.columns(2)
                with ca:
                    table_name = st.selectbox("Tabela", options=table_names, key="impact_table")
                    selected_table = next(
                        (t for t in meta.business_tables if t.name == table_name), None
                    ) if meta else None
                    col_names = (
                        [c.name for c in selected_table.columns]
                        if selected_table and selected_table.columns
                        else ["Amount"]
                    )
                    old_name = st.selectbox("Coluna", options=col_names, key="impact_col")
                with cb:
                    new_name = st.text_input("Novo nome", value="") if change_type == "rename_column" else ""
 
            elif change_type == "rename_measure":
                ca, cb = st.columns(2)
                all_measures = [
                    (t.name, m.name)
                    for t in meta.business_tables
                    for m in t.measures
                ]
                measure_labels = [f"{t}.{m}" for t, m in all_measures] if all_measures else ["Medida"]
                with ca:
                    selected_measure = st.selectbox("Medida", options=measure_labels, key="impact_measure")
                    parts = selected_measure.split(".", 1)
                    table_name = parts[0] if len(parts) == 2 else ""
                    old_name = parts[1] if len(parts) == 2 else parts[0]
                with cb:
                    new_name = st.text_input("Novo nome da medida", value="")
 
            else:
                ca, cb = st.columns(2)
                with ca:
                    table_name = st.selectbox(
                        "Tabela a renomear", options=table_names, key="impact_rename_table"
                    )
                with cb:
                    new_name = st.text_input(
                        "Novo nome da tabela",
                        value=f"{table_names[0]}Data" if table_names else "SalesData",
                    )
                old_name = table_name
 
        if st.button("Analisar impacto", type="primary", use_container_width=True):
            with st.status("Analisando dependências...", expanded=True) as _impact_status:
                try:
                    if not graph:
                        st.error("Grafo de dependências não disponível. Reconecte o modelo.")
                        st.stop()
 
                    type_map = {
                        "rename_column": ChangeType.RENAME_COLUMN,
                        "rename_table": ChangeType.RENAME_TABLE,
                        "rename_measure": ChangeType.RENAME_MEASURE,
                        "delete_column": ChangeType.DELETE_COLUMN,
                    }
                    ct = type_map[change_type]
 
                    change = ProposedChange(
                        change_type=ct,
                        table_name=table_name if change_type != "rename_table" else None,
                        object_name=old_name,
                        new_value=new_name if new_name else None,
                        validate_before_apply=True,
                        dry_run=False,
                        auto_rollback_on_failure=True,
                    )
 
                    from pbi_refactor_agent.discovery import ImpactAnalyzer
                    analyzer = ImpactAnalyzer(graph, metadata=meta)
                    extended = analyzer.analyze_extended(change)
                    impact = extended.base
 
                    details = []
 
                    for imp in impact.direct_impacts:
                        details.append({
                            "Categoria": "Direto",
                            "Tipo": _label_object_type(imp.object.object_type),
                            "Nome": imp.object.name,
                            "Tabela": imp.object.table_name or "—",
                            "DAX Original": _truncate(imp.original_expression),
                            "DAX Após Mudança": _truncate(imp.suggested_expression)
                                if imp.suggested_expression
                                else "⚠️ Requer revisão manual",
                            "Revisão Manual": "⚠️ Sim" if imp.requires_manual_review else "✓ Não",
                        })
 
                    for imp in impact.cascade_impacts:
                        details.append({
                            "Categoria": "Cascata",
                            "Tipo": _label_object_type(imp.object.object_type),
                            "Nome": imp.object.name,
                            "Tabela": imp.object.table_name or "—",
                            "DAX Original": _truncate(imp.original_expression),
                            "DAX Após Mudança": "⚠️ Requer revisão manual",
                            "Revisão Manual": "⚠️ Sim",
                        })
 
                    for rel in impact.relationship_impacts:
                        if any(
                            rel.from_table.startswith(p) or rel.to_table.startswith(p)
                            for p in ("LocalDateTable_", "DateTableTemplate_", "ParameterTable_")
                        ):
                            continue
                        details.append({
                            "Categoria": "Relacionamento",
                            "Tipo": "Relacionamento",
                            "Nome": rel.name or f"{rel.from_table} → {rel.to_table}",
                            "Tabela": rel.from_table,
                            "DAX Original": f"{rel.from_table}[{rel.from_column}] → {rel.to_table}[{rel.to_column}]",
                            "DAX Após Mudança": "Chave do relacionamento impactada",
                            "Revisão Manual": "⚠️ Sim",
                        })
 
                    for h in extended.hierarchy_impacts:
                        details.append({
                            "Categoria": "Hierarquia",
                            "Tipo": "Hierarquia",
                            "Nome": f"{h.hierarchy_name} — {h.affected_level}",
                            "Tabela": h.table_name,
                            "DAX Original": f"Nível '{h.affected_level}' referencia '{h.affected_column}'",
                            "DAX Após Mudança": h.impact_description,
                            "Revisão Manual": "⚠️ Sim",
                        })
 
                    for s in extended.sort_by_impacts:
                        details.append({
                            "Categoria": "Ordenação",
                            "Tipo": "sortByColumn",
                            "Nome": s.column_name,
                            "Tabela": s.table_name,
                            "DAX Original": f"'{s.column_name}' ordenada por '{s.sort_by_column}'",
                            "DAX Após Mudança": s.impact_description,
                            "Revisão Manual": "⚠️ Sim",
                        })
 
                    # KPIs
                    for k in extended.kpi_impacts:
                        details.append({
                            "Categoria": "KPI",
                            "Tipo": "KPI",
                            "Nome": k.measure_name,
                            "Tabela": k.table_name,
                            "DAX Original": _truncate(k.target_expression or k.status_expression or ""),
                            "DAX Após Mudança": k.impact_description,
                            "Revisão Manual": "⚠️ Sim",
                        })
 
                    # Label da mudança
                    if change_type == "rename_table":
                        change_label = f"{old_name} → {new_name}"
                    elif new_name:
                        change_label = f"{table_name}.{old_name} → {new_name}"
                    else:
                        change_label = f"DELETE {table_name}.{old_name}"
 
                    real_rels = [
                        rel for rel in impact.relationship_impacts
                        if not any(
                            rel.from_table.startswith(p) or rel.to_table.startswith(p)
                            for p in ("LocalDateTable_", "DateTableTemplate_", "ParameterTable_")
                        )
                    ]

                    impact_result = {
                        "change": change_label,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "total_impacted": (
                            len(impact.direct_impacts)
                            + len(impact.cascade_impacts)
                            + len(real_rels)
                            + len(extended.hierarchy_impacts)
                            + len(extended.sort_by_impacts)
                            + len(extended.kpi_impacts)
                        ),
                        "direct_impacts": len(impact.direct_impacts),
                        "cascade_impacts": len(impact.cascade_impacts),
                        "relationship_impacts": len(real_rels),
                        "hierarchy_impacts": len(extended.hierarchy_impacts),
                        "sort_by_impacts": len(extended.sort_by_impacts),
                        "kpi_impacts": len(extended.kpi_impacts),
                        "details": details,
                        "impact_analysis": impact,
                    }
 
                    st.session_state.impact_results.append(impact_result)
 
                    total = extended.total_extended_impacts
                    _impact_status.update(
                        label=f"Análise concluída — {total} impacto(s)",
                        state="complete",
                        expanded=False,
                    )
                    st.toast(f"Análise concluída: {total} impacto(s)", icon="🔍")
 
                    st.markdown('<p class="section-label">Resultado</p>', unsafe_allow_html=True)
 
                    cols_kpi = st.columns(7)
                    cols_kpi[0].metric("Total", impact_result["total_impacted"])
                    cols_kpi[1].metric("Medidas DAX", impact_result["direct_impacts"])
                    cols_kpi[2].metric("Cascata", impact_result["cascade_impacts"])
                    cols_kpi[3].metric("Relacionamentos", impact_result["relationship_impacts"])
                    cols_kpi[4].metric("Hierarquias", impact_result["hierarchy_impacts"])
                    cols_kpi[5].metric("Ordenações", impact_result["sort_by_impacts"])
                    cols_kpi[6].metric("KPIs", impact_result["kpi_impacts"])
 
                    chart_labels = []
                    chart_values = []
                    for label, key in [
                        ("Medidas DAX", "direct_impacts"),
                        ("Cascata", "cascade_impacts"),
                        ("Relacionamentos", "relationship_impacts"),
                        ("Hierarquias", "hierarchy_impacts"),
                        ("Ordenações", "sort_by_impacts"),
                        ("KPIs", "kpi_impacts"),
                    ]:
                        v = impact_result[key]
                        if v > 0:
                            chart_labels.append(label)
                            chart_values.append(v)
 
                    if chart_values:
                        fig = go.Figure(
                            data=[go.Pie(
                                labels=chart_labels,
                                values=chart_values,
                                hole=0.4,
                                marker_colors=PLOTLY_COLORS[:len(chart_labels)],
                            )]
                        )
                        fig.update_layout(PLOTLY_LAYOUT)
                        fig.update_layout(
                            title="Distribuição de impactos",
                            height=380,
                        )
                        st.plotly_chart(fig, use_container_width=True)
 
                    st.markdown(
                        '<p class="section-label">Objetos impactados</p>',
                        unsafe_allow_html=True,
                    )
 
                    if details:
                        df_impact = pd.DataFrame(details)
 
                        # Filtro por categoria
                        categorias_disponiveis = sorted(df_impact["Categoria"].unique().tolist())
                        categorias_sel = st.multiselect(
                            "Filtrar por categoria",
                            options=categorias_disponiveis,
                            default=categorias_disponiveis,
                            key="impact_cat_filter",
                        )
                        df_filtrado = df_impact[df_impact["Categoria"].isin(categorias_sel)]
 
                        st.dataframe(
                            df_filtrado,
                            column_config={
                                "Categoria": st.column_config.TextColumn("Categoria", width="small"),
                                "Tipo": st.column_config.TextColumn("Tipo", width="medium"),
                                "Nome": st.column_config.TextColumn("Nome", width="large"),
                                "Tabela": st.column_config.TextColumn("Tabela", width="medium"),
                                "DAX Original": st.column_config.TextColumn("DAX Original", width="large"),
                                "DAX Após Mudança": st.column_config.TextColumn("DAX Após Mudança", width="large"),
                                "Revisão Manual": st.column_config.TextColumn("Revisão", width="small"),
                            },
                            hide_index=True,
                            use_container_width=True,
                        )
 
                        if impact.direct_impacts:
                            st.markdown(
                                '<p class="section-label" style="margin-top:1.5rem;">'
                                "DAX completo dos impactos diretos</p>",
                                unsafe_allow_html=True,
                            )
                            for imp in impact.direct_impacts:
                                obj = imp.object
                                label_type = _label_object_type(obj.object_type)
                                with st.expander(
                                    f"{label_type} — {obj.name} ({obj.table_name or '—'})"
                                ):
                                    col_a, col_b = st.columns(2)
                                    with col_a:
                                        st.caption("**DAX Original**")
                                        st.code(imp.original_expression or "—", language="dax")
                                    with col_b:
                                        st.caption("**DAX Após Mudança (sugerido)**")
                                        st.code(
                                            imp.suggested_expression or "⚠️ Requer revisão manual",
                                            language="dax",
                                        )
                                    if imp.requires_manual_review:
                                        st.warning(
                                            "Esta expressão é complexa e pode precisar de ajuste manual."
                                        )
                                    if imp.notes:
                                        st.caption(f"Nota: {imp.notes}")
 
                        if extended.hierarchy_impacts:
                            st.markdown(
                                '<p class="section-label" style="margin-top:1.5rem;">'
                                "Hierarquias impactadas</p>",
                                unsafe_allow_html=True,
                            )
                            for h in extended.hierarchy_impacts:
                                with st.expander(
                                    f"Hierarquia — {h.hierarchy_name} ({h.table_name})"
                                ):
                                    st.warning(h.impact_description)
                                    st.caption(f"Nível afetado: **{h.affected_level}**")
                                    st.caption(f"Coluna referenciada: **{h.affected_column}**")
 
                        if extended.sort_by_impacts:
                            st.markdown(
                                '<p class="section-label" style="margin-top:1.5rem;">'
                                "Ordenações impactadas (sortByColumn)</p>",
                                unsafe_allow_html=True,
                            )
                            for s in extended.sort_by_impacts:
                                with st.expander(
                                    f"Ordenação — {s.table_name}[{s.column_name}]"
                                ):
                                    st.warning(s.impact_description)
                                    st.caption(
                                        f"A coluna **'{s.column_name}'** usa **'{s.sort_by_column}'** "
                                        f"para ordenação. Se a coluna de ordenação for alterada, "
                                        f"a ordem de exibição quebrará nos visuais."
                                    )
 
                        if extended.kpi_impacts:
                            st.markdown(
                                '<p class="section-label" style="margin-top:1.5rem;">'
                                "KPIs impactados</p>",
                                unsafe_allow_html=True,
                            )
                            for k in extended.kpi_impacts:
                                with st.expander(
                                    f"KPI — {k.measure_name} ({k.table_name})"
                                ):
                                    st.warning(k.impact_description)
                                    if k.target_expression:
                                        st.caption("**Target expression:**")
                                        st.code(k.target_expression, language="dax")
                                    if k.status_expression:
                                        st.caption("**Status expression:**")
                                        st.code(k.status_expression, language="dax")
 
                    else:
                        st.info("Nenhum objeto impactado encontrado para esta mudança.")
 
                    if details:
                        st.divider()
                        reporter = ReportGenerator()
                        report_md = reporter.generate_impact_report(impact, format="markdown")
                        st.download_button(
                            "Download relatório (Markdown)",
                            data=report_md,
                            file_name=f"impacto_{old_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                            mime="text/markdown",
                        )
 
                except Exception as e:
                    st.error(f"Erro na análise: {e}")
                    import traceback
                    st.code(traceback.format_exc())

with tab_refactor:
    st.markdown('<p class="section-label">Refatoração automática</p>', unsafe_allow_html=True)

    if not st.session_state.impact_results:
        st.info("Faça uma análise de impacto primeiro.")
    else:
        selected_analysis = st.selectbox(
            "Análise para refatorar",
            options=range(len(st.session_state.impact_results)),
            format_func=lambda i: (
                f"{st.session_state.impact_results[i]['change']}  "
                f"({st.session_state.impact_results[i]['total_impacted']} impactos)"
            ),
        )

        analysis = st.session_state.impact_results[selected_analysis]

        c1, c2, c3 = st.columns(3, gap="large")
        c1.metric("Objetos a refatorar", analysis["total_impacted"])
        c2.metric("LLM selecionado", llm_provider.upper())
        c3.metric("Validação", "Ativa" if validate_syntax else "Desativada")

        c1, c2 = st.columns(2)
        with c1:
            dry_run = st.checkbox(
                "Modo dry-run (simular sem aplicar)",
                value=not auto_apply,
            )
        with c2:
            generate_report = st.checkbox("Gerar relatório", value=True)

        if st.button("Iniciar refatoração", type="primary", width="stretch"):
            with st.status("Refatorando expressões DAX...", expanded=True) as status:
                try:
                    impact_analysis = analysis.get("impact_analysis")

                    if impact_analysis is None:
                        st.error(
                            "Esta análise não possui dados de impacto completos. "
                            "Refaça a análise de impacto (change_datatype não suporta refatoração automática)."
                        )
                        st.stop()

                    if impact_analysis.total_impacted == 0:
                        st.warning("Nenhum objeto com expressão DAX para refatorar.")
                        st.stop()

                    st.write(f"Conectando ao {llm_provider.upper()}...")

                    dax_refactor = cached_dax_refactor()

                    st.write(
                        f"Refatorando {impact_analysis.total_impacted} expressão(ões) com {llm_provider.upper()}..."
                    )

                    result = asyncio.run(
                        dax_refactor.refactor(
                            impact_analysis=impact_analysis,
                            llm_provider=LLMProvider(llm_provider),
                            llm_model=llm_model,
                        )
                    )

                    st.write("Processando resultados...")

                    successful = sum(1 for item in result.items if item.refactored_expression)
                    failed = len(result.items) - successful

                    refactor_result = {
                        "change": analysis["change"],
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": result.status.value,
                        "impacts": len(result.items),
                        "successes": successful,
                        "failures": failed,
                        "warnings": 0,
                        "time": result.duration_seconds or 0.0,
                        "applied": not dry_run,
                        "items": result.items,
                    }

                    st.session_state.refactor_history.append(refactor_result)
                    status.update(
                        label=f"Refatoração concluída — {successful}/{len(result.items)} sucesso(s)",
                        state="complete",
                        expanded=False,
                    )

                    st.toast(f"Refatoração concluída: {successful} sucesso(s)", icon="✅")

                    st.markdown('<p class="section-label">Resultado</p>', unsafe_allow_html=True)

                    c1, c2, c3, c4 = st.columns(4)
                    total_items = max(refactor_result["impacts"], 1)
                    pct = refactor_result["successes"] / total_items * 100
                    c1.metric("Sucesso", refactor_result["successes"], delta=f"{pct:.0f}%")
                    c2.metric("Falhas", refactor_result["failures"])
                    c3.metric("Avisos", refactor_result["warnings"])
                    c4.metric("Tempo", f"{refactor_result['time']:.2f}s")

                    fig = go.Figure(
                        data=[
                            go.Bar(
                                x=["Sucesso", "Falhas", "Avisos"],
                                y=[
                                    refactor_result["successes"],
                                    refactor_result["failures"],
                                    refactor_result["warnings"],
                                ],
                                marker_color=["#34D399", "#F87171", "#FBBF24"],
                            )
                        ]
                    )
                    fig.update_layout(PLOTLY_LAYOUT)
                    fig.update_layout(title="Resultado da refatoração", yaxis_title="Quantidade", height=380, showlegend=False)
                    st.plotly_chart(fig, width="stretch")

                    if refactor_result.get("items"):
                        syntax_validator = SyntaxValidator()
                        validation_results = []
                        for item in refactor_result["items"]:
                            if item.refactored_expression:
                                vr = syntax_validator.validate(item.refactored_expression)
                                validation_results.append(vr)
                            else:
                                validation_results.append(SyntaxValidation(is_valid=False, error_message="Sem expressão", error_line=0, error_column=0))

                        syntax_ok = sum(1 for v in validation_results if v.is_valid)
                        syntax_fail = len(validation_results) - syntax_ok

                        st.markdown('<p class="section-label">Validação Sintática (OE4)</p>', unsafe_allow_html=True)
                        vc1, vc2, vc3 = st.columns(3, gap="large")
                        vc1.metric("Sintaxe OK", syntax_ok)
                        vc2.metric("Sintaxe Falha", syntax_fail)
                        vc3.metric("Taxa de Aprovação", f"{syntax_ok / max(len(validation_results), 1) * 100:.0f}%")

                        st.markdown('<p class="section-label" style="margin-top:1.5rem;">Expressões refatoradas</p>', unsafe_allow_html=True)
                        for idx, item in enumerate(refactor_result["items"]):
                            obj = item.object
                            label = f"{obj.name} ({obj.table_name or '—'})"
                            vr = validation_results[idx]
                            if item.refactored_expression and vr.is_valid:
                                status_label = "[OK]"
                                syntax_badge = '<span class="badge-success">Sintaxe válida</span>'
                            elif item.refactored_expression:
                                status_label = "[ATENÇÃO]"
                                syntax_badge = f'<span class="badge-warning">Sintaxe: {vr.error_message}</span>'
                            else:
                                status_label = "[ERRO]"
                                syntax_badge = '<span class="badge-error">Sem expressão</span>'

                            with st.expander(f"{status_label} {label}  —  confiança: {item.confidence_score:.0%}"):
                                st.markdown(syntax_badge, unsafe_allow_html=True)
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    st.caption("**Original**")
                                    st.code(item.original_expression or "—", language="dax")
                                with col_b:
                                    st.caption("**Refatorada**")
                                    st.code(item.refactored_expression or "Sem sugestão", language="dax")

                    if not dry_run:
                        st.markdown(
                            '<div class="alert-info">'
                            "<strong>Pronto para aplicar.</strong> "
                            "Clique abaixo para gerar o .pbit com o renomeio completo aplicado."
                            "</div>",
                            unsafe_allow_html=True,
                        )

                        pbit_path = None
                        data_dir = Path("data")
                        if data_dir.exists():
                            pbit_files = list(data_dir.glob("*.pbit"))
                            if pbit_files:
                                pbit_path = pbit_files[0]

                        if pbit_path and st.session_state.get("model_metadata"):
                            valid_items = [
                                item for item in refactor_result["items"]
                                if item.refactored_expression
                            ]

                            selected_impact = st.session_state.impact_results[selected_analysis]
                            change_label = selected_impact.get("change", "")
                            impact_base = selected_impact.get("impact_analysis")

                            if impact_base:
                                _change_type_map = {
                                    "rename_column": "rename_column",
                                    "rename_table": "rename_table",
                                    "rename_measure": "rename_measure",
                                }
                                _ct = str(impact_base.change_type.value)

                                if _ct in _change_type_map:
                                    try:
                                        from pbi_refactor_agent.utils.schema_patcher import apply_structural_rename

                                        out_path = apply_structural_rename(
                                            original_path=str(pbit_path),
                                            change_type=_ct,
                                            table_name=impact_base.target_object.table_name,
                                            old_name=impact_base.target_object.name,
                                            new_name=impact_base.new_value or "",
                                            refactored_items=valid_items,
                                        )

                                        with open(out_path, "rb") as pf:
                                            st.download_button(
                                                "⬇️ Download .pbit completo (renomeio + DAX corrigido)",
                                                data=pf.read(),
                                                file_name=Path(out_path).name,
                                                mime="application/octet-stream",
                                                type="primary",
                                                use_container_width=True,
                                            )

                                        st.markdown(
                                            '<div class="alert-success">'
                                            "<strong>.pbit gerado com sucesso.</strong><br>"
                                            "O arquivo contém:<br>"
                                            f"✓ Coluna/tabela/medida renomeada no schema<br>"
                                            f"✓ {len(valid_items)} expressão(ões) DAX refatorada(s) pelo LLM<br>"
                                            f"✓ Relacionamentos atualizados<br>"
                                            f"✓ Hierarquias atualizadas<br>"
                                            "Abra no Power BI Desktop para verificar."
                                            "</div>",
                                            unsafe_allow_html=True,
                                        )

                                    except Exception as wb_err:
                                        st.warning(f"Erro ao gerar .pbit: {wb_err}")
                                        import traceback
                                        st.code(traceback.format_exc())
                                else:
                                    st.info(
                                        "Este tipo de mudança (delete) requer revisão manual "
                                        "antes de aplicar ao modelo."
                                    )
                            else:
                                st.warning(
                                    "Dados da análise de impacto não disponíveis. "
                                    "Refaça a análise de impacto antes de aplicar."
                                )
                        else:
                            st.warning("Arquivo .pbit não encontrado na pasta `data/`.")
                    else:
                        st.markdown(
                            '<div class="alert-warning">'
                            "<strong>Modo dry-run.</strong> "
                            "Nenhuma mudança foi aplicada. Desmarque a opção para gerar o .pbit refatorado."
                            "</div>",
                            unsafe_allow_html=True,
                        )

                except Exception as e:
                    st.error(f"Erro na refatoração: {e}")

with tab_history:
    st.markdown('<p class="section-label">Histórico de refatorações</p>', unsafe_allow_html=True)

    if not st.session_state.refactor_history:
        st.info("Nenhuma refatoração realizada ainda.")
    else:
        total_refactors = len(st.session_state.refactor_history)
        total_successes = sum(r["successes"] for r in st.session_state.refactor_history)
        total_failures = sum(r["failures"] for r in st.session_state.refactor_history)
        avg_time = (
            sum(r["time"] for r in st.session_state.refactor_history) / total_refactors
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Refatorações", total_refactors)
        c2.metric("Sucessos", total_successes)
        c3.metric("Falhas", total_failures)
        c4.metric("Tempo médio", f"{avg_time:.2f}s")

        st.divider()

        df_history = pd.DataFrame(st.session_state.refactor_history)

        fig = px.bar(
            df_history,
            x="timestamp",
            y=["successes", "failures"],
            title="Sucesso vs falhas por refatoração",
            labels={"value": "Quantidade", "variable": "Tipo"},
            color_discrete_map={"successes": "#34D399", "failures": "#F87171"},
        )
        fig.update_layout(PLOTLY_LAYOUT)
        fig.update_layout(height=380)
        st.plotly_chart(fig, width="stretch")

        st.markdown('<p class="section-label">Detalhes</p>', unsafe_allow_html=True)

        st.dataframe(
            df_history[
                ["timestamp", "change", "successes", "failures", "time", "applied"]
            ],
            column_config={
                "timestamp": st.column_config.TextColumn("Data/Hora"),
                "change": st.column_config.TextColumn("Mudança", width="large"),
                "successes": st.column_config.NumberColumn("Sucesso", format="%d"),
                "failures": st.column_config.NumberColumn("Falhas", format="%d"),
                "time": st.column_config.NumberColumn("Tempo (s)", format="%.2f"),
                "applied": st.column_config.CheckboxColumn("Aplicado"),
            },
            hide_index=True,
            width="stretch",
        )

        st.divider()
        st.markdown('<p class="section-label">Exportar</p>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)

        with c1:
            csv = df_history.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"refactor_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

        with c2:
            st.button("Gerar relatório PDF", disabled=True, help="Em desenvolvimento")

st.markdown('<div style="height: 2rem;"></div>', unsafe_allow_html=True)

st.markdown(
    '<div style="text-align:center; padding: 1.5rem 0 0.5rem; border-top: 1px solid rgba(55,65,81,0.25);">'
    '<p class="footer">'
    'PBI Refactor Agent v1.0 &nbsp;—&nbsp; '
    'Isabella da Silva Moura &nbsp;—&nbsp; '
    'TCC FAETERJ 2026'
    '</p>'
    '</div>',
    unsafe_allow_html=True,
)