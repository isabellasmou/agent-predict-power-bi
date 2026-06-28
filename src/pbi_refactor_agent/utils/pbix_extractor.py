"""
Extrator de metadados de modelos Power BI (.pbit).

Extrai o DataModelSchema (JSON) de dentro do arquivo .pbit (ZIP)
e retorna metadados estruturados: tabelas, colunas, medidas (DAX),
relacionamentos, hierarquias, sortByColumn e KPIs.

Nota: Apenas .pbit e suportado. Para gerar um .pbit a partir de .pbix:
  Power BI Desktop > Arquivo > Exportar > Modelo do Power BI (.pbit)
"""

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class HierarchyLevel:
    """Nível de uma hierarquia."""
    name: str
    column: str
    ordinal: int = 0


@dataclass
class HierarchyMetadata:
    """Metadados de uma hierarquia."""
    name: str
    table_name: str
    levels: list = field(default_factory=list)  # list[HierarchyLevel]
    is_hidden: bool = False


@dataclass
class KPIMetadata:
    """Metadados de um KPI associado a uma medida."""
    target_expression: Optional[str] = None
    target_measure: Optional[str] = None
    status_expression: Optional[str] = None
    trend_expression: Optional[str] = None


@dataclass
class ColumnMetadata:
    """Metadados de uma coluna."""
    name: str
    data_type: str = "unknown"
    is_hidden: bool = False
    source_column: str = ""
    format_string: str = ""
    category: str = "other"
    expression: Optional[str] = None
    sort_by_column: Optional[str] = None  # NOVO: coluna usada para ordenar esta


@dataclass
class MeasureMetadata:
    """Metadados de uma medida."""
    name: str
    expression: str = ""
    formatted_expression: str = ""
    format_string: str = ""
    is_hidden: bool = False
    display_folder: str = ""
    category: str = "other"
    complexity: str = "simple"
    description: str = ""
    kpi: Optional[KPIMetadata] = None  # NOVO: KPI associado


@dataclass
class RelationshipMetadata:
    """Metadados de um relacionamento."""
    name: str = ""
    from_table: str = ""
    from_column: str = ""
    to_table: str = ""
    to_column: str = ""
    cardinality: str = "many:one"
    cross_filtering: str = "OneDirection"
    is_active: bool = True


@dataclass
class TableMetadata:
    """Metadados de uma tabela."""
    name: str
    is_hidden: bool = False
    is_technical: bool = False
    columns: list = field(default_factory=list)   # list[ColumnMetadata]
    measures: list = field(default_factory=list)  # list[MeasureMetadata]
    hierarchies: list = field(default_factory=list)  # NOVO: list[HierarchyMetadata]
    partition_count: int = 0


@dataclass
class ModelMetadata:
    """Metadados completos do modelo."""
    file_name: str
    file_type: str
    extraction_method: str
    compatibility_level: str = "unknown"
    tables: list = field(default_factory=list)         # list[TableMetadata]
    relationships: list = field(default_factory=list)  # list[RelationshipMetadata]
    hierarchies: list = field(default_factory=list)    # NOVO: todas as hierarquias do modelo

    @property
    def business_tables(self):
        return [t for t in self.tables if not t.is_technical]

    @property
    def total_columns(self) -> int:
        return sum(len(t.columns) for t in self.business_tables)

    @property
    def total_measures(self) -> int:
        return sum(len(t.measures) for t in self.business_tables)

    @property
    def total_hierarchies(self) -> int:
        return len(self.hierarchies)

    @property
    def summary(self) -> dict:
        return {
            "file_name": self.file_name,
            "file_type": self.file_type,
            "extraction_method": self.extraction_method,
            "total_tables": len(self.tables),
            "business_tables": len(self.business_tables),
            "technical_tables": len(self.tables) - len(self.business_tables),
            "total_columns": self.total_columns,
            "total_measures": self.total_measures,
            "total_relationships": len(self.relationships),
            "total_hierarchies": self.total_hierarchies,
        }


# ============================================================================
# Extraction Errors
# ============================================================================

class ExtractionError(Exception):
    """Erro base de extracao."""
    pass


# ============================================================================
# Categorization
# ============================================================================

TECHNICAL_TABLE_PREFIXES = [
    "LocalDateTable_",
    "DateTableTemplate_",
    "ParameterTable_",
]


def is_technical_table(table_name: str) -> bool:
    return any(table_name.startswith(p) for p in TECHNICAL_TABLE_PREFIXES)


def categorize_measure(name: str, expression: Optional[str] = None) -> str:
    """
    Categoriza medidas com base no nome e expressão DAX.

    Usa sistema de pontuação por categoria — expressão DAX tem peso maior
    que nome. Evita o problema de "primeira condição que bate vence".
    """
    n = (name or "").lower()
    e = (expression or "").lower()

    scores: dict[str, int] = {
        "revenue": 0,
        "cost": 0,
        "margin": 0,
        "percentage": 0,
        "ratio": 0,
        "temporal": 0,
        "calendar_intelligence": 0,
        "aggregation": 0,
        "filtering": 0,
        "other": 0,
    }

    # ── Expressão DAX (peso 2-3) ──────────────────────────────

    # Calendar Intelligence — detectar antes de temporal
    if any(x in e for x in [
        "datesytd", "datesmtd", "datesqtd", "dateadd",
        "parallelperiod", "sameperiodlastyear",
        "totalytd", "totalmtd", "totalqtd",
        "previousyear", "previousmonth", "previousquarter",
        "nextyear", "nextmonth", "nextquarter",
    ]):
        scores["calendar_intelligence"] += 3

    # Ratio — DIVIDE ou divisão explícita
    if "divide(" in e:
        scores["ratio"] += 3
    if re.search(r'(?<![/])/(?![/])', e):
        scores["ratio"] += 2

    # Margin — combinação de receita e custo
    if any(x in e for x in ["margin", "margem", "lucro", "profit"]):
        scores["margin"] += 3
    if (any(x in e for x in ["revenue", "receita", "venda"]) and
            any(x in e for x in ["cost", "custo", "despesa"])):
        scores["margin"] += 2

    # Percentage — FORMAT com % ou comparação relativa
    if "%" in e or "percent" in e or "porcentagem" in e:
        scores["percentage"] += 3
    if re.search(r'divide\(.*\)', e) and any(x in n for x in ["%", "percent", "taxa", "ratio", "pct"]):
        scores["percentage"] += 2

    # Temporal — funções de data sem time intelligence
    if any(x in e for x in ["date(", "year(", "month(", "day(", "eomonth", "datediff", "calendar("]):
        scores["temporal"] += 2

    # Filtering — funções de filtro como propósito principal
    if any(x in e for x in [
        "selectedvalue(", "hasonevalue(", "hasonefilter(",
        "isfiltered(", "iscrossfiltered(",
    ]):
        scores["filtering"] += 3
    if e.count("filter(") >= 2 or e.count("all(") >= 2:
        scores["filtering"] += 2

    # Aggregation — funções de agregação simples
    if any(x in e for x in ["sum(", "count(", "average(", "countrows(", "distinctcount(", "countblank("]):
        scores["aggregation"] += 2
    if any(x in e for x in ["sumx(", "averagex(", "countx(", "maxx(", "minx("]):
        scores["aggregation"] += 1

    # Revenue / Cost pela expressão
    if any(x in e for x in ["receita", "faturamento", "revenue"]):
        scores["revenue"] += 2
    if any(x in e for x in ["custo", "despesa", "cost", "expense"]):
        scores["cost"] += 2

    # ── Nome da medida (peso 1-2) ─────────────────────────────

    if any(x in n for x in ["ytd", "mtd", "qtd", "sply", "acumulado", "last year", "last month"]):
        scores["calendar_intelligence"] += 2

    if any(x in n for x in ["%", "percent", "porcentagem", "pct", "taxa de"]):
        scores["percentage"] += 2

    if any(x in n for x in ["ratio", "razão", "razao", "índice", "indice", "proporção", "proporcao"]):
        scores["ratio"] += 2

    if any(x in n for x in ["margin", "margem", "lucro", "profit"]):
        scores["margin"] += 2

    if any(x in n for x in ["revenue", "sales", "venda", "receita", "faturamento"]):
        scores["revenue"] += 1

    if any(x in n for x in ["cost", "custo", "expense", "despesa", "gasto"]):
        scores["cost"] += 1

    if any(x in n for x in [
        "year", "ano", "month", "mes", "mês", "quarter",
        "trimestre", "period", "período", "periodo", "semana", "week",
    ]):
        scores["temporal"] += 1

    if any(x in n for x in ["total", "sum", "soma", "count", "contagem", "quantidade", "media", "média", "average"]):
        scores["aggregation"] += 1

    # Retorna a categoria com maior pontuação
    best = max(scores, key=lambda k: (scores[k], k != "other"))

    if scores[best] == 0:
        return "other"

    return best


def categorize_column(data_type: str, name: str) -> str:
    n = (name or "").lower()
    if any(x in n for x in ["id", "sk.", "ck.", "key", "chave"]):
        return "identifier"
    if data_type in ("dateTime", "date") or any(x in n for x in ["date", "data", "fecha"]):
        return "temporal"
    if data_type in ("int64", "double", "decimal"):
        if any(x in n for x in ["amount", "total", "count", "monto", "valor", "quantidade"]):
            return "metric"
        return "numeric"
    if data_type == "string":
        if any(x in n for x in ["name", "nome", "description", "descricao"]):
            return "descriptive"
        return "categorical"
    return "other"


CATEGORY_LABELS_PT = {
    "revenue": "Receita",
    "cost": "Custo",
    "margin": "Margem",
    "percentage": "Percentual",
    "ratio": "Razão",
    "temporal": "Temporal",
    "calendar_intelligence": "Inteligência de Calendário",
    "aggregation": "Agregação",
    "filtering": "Filtragem",
    "other": "Outras",
    "identifier": "Identificador",
    "numeric": "Numérico",
    "metric": "Métrica",
    "descriptive": "Descritivo",
    "categorical": "Categórico",
}


# ============================================================================
# DAX Formatting
# ============================================================================

def clean_dax(expression) -> str:
    if not expression:
        return ""
    if isinstance(expression, list):
        expression = " ".join(str(item) for item in expression)
    expression = str(expression)
    lines = [line.rstrip() for line in expression.split("\n") if line.strip()]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned


def format_dax(expression: str) -> str:
    if not expression or not expression.strip():
        return ""
    cleaned = clean_dax(expression)
    complex_funcs = [
        "CALCULATE", "IF", "SWITCH", "FILTER", "TOTALYTD",
        "TOTALQTD", "TOTALMTD", "SAMEPERIODLASTYEAR", "DATESYTD", "DIVIDE",
    ]
    formatted = cleaned
    for func in complex_funcs:
        pattern = rf"\b({func})\s*\("
        formatted = re.sub(pattern, rf"\1(\n    ", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r",\s*", ",\n    ", formatted)
    formatted = re.sub(r"\n\s*\n", "\n", formatted)
    return formatted.strip()


def dax_complexity_score(expression: str) -> int:
    if not expression:
        return 0
    score = 0
    for func in ["IF", "SWITCH", "CALCULATE", "FILTER", "ALL", "VALUES"]:
        score += expression.upper().count(func) * 3
    for op in ["+", "-", "*", "/", "=", "<", ">", "!"]:
        score += expression.count(op)
    nesting = 0
    max_nesting = 0
    for ch in expression:
        if ch == "(":
            nesting += 1
            max_nesting = max(max_nesting, nesting)
        elif ch == ")":
            nesting -= 1
    score += max_nesting * 2
    score += len(expression) // 50
    return score


def dax_complexity_label(expression: str) -> str:
    s = dax_complexity_score(expression)
    if s <= 5:
        return "simple"
    if s <= 15:
        return "medium"
    return "complex"


# ============================================================================
# .pbit Extractor
# ============================================================================

def _clean_json_text(text: str) -> str:
    cleaned = text.lstrip("\ufeff").replace("\x00", "")
    cleaned = re.sub(r"(^|[\s{,\[])[ \t]*//.*?$", r"\1", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def _parse_json_bytes(raw_bytes: bytes, filename: str) -> dict:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractionError(f"Nao foi possivel decodificar {filename}")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = _clean_json_text(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ExtractionError(f"Erro ao parsear JSON de {filename}: {e}")


def extract_from_pbit(file_path: Path) -> ModelMetadata:
    if not file_path.exists():
        raise ExtractionError(f"Arquivo nao encontrado: {file_path}")

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            files = zf.namelist()
            schema_files = [f for f in files if any(
                k in f for k in ("DataModelSchema", "DataModel", "model.json")
            )]
            if not schema_files:
                raise ExtractionError(
                    f"DataModelSchema nao encontrado. Arquivos: {', '.join(files[:10])}"
                )

            schema = None
            for sf in schema_files:
                try:
                    raw = zf.read(sf)
                    schema = _parse_json_bytes(raw, sf)
                    if "model" in schema:
                        break
                except Exception:
                    continue

            if not schema or "model" not in schema:
                raise ExtractionError("Nenhum schema valido encontrado no arquivo")

            return _process_schema(schema, file_path.name, "pbit")
    except zipfile.BadZipFile:
        raise ExtractionError(f"Arquivo ZIP invalido: {file_path}")


def _process_schema(schema: dict, file_name: str, file_type: str) -> ModelMetadata:
    """Processa schema JSON e retorna metadados estruturados."""
    model = schema["model"]
    tables_raw = model.get("tables", [])
    rels_raw = model.get("relationships", [])

    metadata = ModelMetadata(
        file_name=file_name,
        file_type=file_type,
        extraction_method="full_schema",
        compatibility_level=str(schema.get("compatibilityLevel", "unknown")),
    )

    all_hierarchies = []

    for table in tables_raw:
        tname = table.get("name", "Unknown")
        is_tech = is_technical_table(tname)

        # ── Colunas ──────────────────────────────────────────
        columns = []
        # Mapeia nome → sortByColumn para pós-processamento
        sort_map: dict[str, str] = {}
        for col in table.get("columns", []):
            dt = col.get("dataType", "unknown")
            cname = col.get("name", "")
            expr = col.get("expression")
            if isinstance(expr, list):
                expr = "\n".join(expr)

            sort_by = col.get("sortByColumn")  # NOVO
            if sort_by:
                sort_map[cname] = sort_by

            columns.append(ColumnMetadata(
                name=cname,
                data_type=dt,
                is_hidden=col.get("isHidden", False),
                source_column=col.get("sourceColumn", ""),
                format_string=col.get("formatString", ""),
                category=categorize_column(dt, cname),
                expression=expr,
                sort_by_column=sort_by,  # NOVO
            ))

        # ── Medidas ───────────────────────────────────────────
        measures = []
        for m in table.get("measures", []):
            raw_expr = m.get("expression", "")
            if isinstance(raw_expr, list):
                raw_expr = "\n".join(raw_expr)
            cleaned = clean_dax(raw_expr)
            mname = m.get("name", "")

            # NOVO: extrair KPI
            kpi_data = m.get("kpi")
            kpi = None
            if kpi_data:
                target_expr = kpi_data.get("targetExpression") or kpi_data.get("targetMeasure")
                if isinstance(target_expr, list):
                    target_expr = "\n".join(target_expr)
                status_expr = kpi_data.get("statusExpression")
                if isinstance(status_expr, list):
                    status_expr = "\n".join(status_expr)
                trend_expr = kpi_data.get("trendExpression")
                if isinstance(trend_expr, list):
                    trend_expr = "\n".join(trend_expr)

                kpi = KPIMetadata(
                    target_expression=target_expr,
                    target_measure=kpi_data.get("targetMeasure"),
                    status_expression=status_expr,
                    trend_expression=trend_expr,
                )

            measures.append(MeasureMetadata(
                name=mname,
                expression=cleaned,
                formatted_expression=format_dax(cleaned),
                format_string=m.get("formatString", ""),
                is_hidden=m.get("isHidden", False),
                display_folder=m.get("displayFolder", ""),
                category=categorize_measure(mname, cleaned),
                complexity=dax_complexity_label(cleaned),
                description=m.get("description", ""),
                kpi=kpi,  # NOVO
            ))

        # ── Hierarquias ───────────────────────────────────────
        hierarchies = []
        for h in table.get("hierarchies", []):
            hname = h.get("name", "")
            levels = []
            for lv in h.get("levels", []):
                levels.append(HierarchyLevel(
                    name=lv.get("name", ""),
                    column=lv.get("column", ""),
                    ordinal=lv.get("ordinal", 0),
                ))
            levels.sort(key=lambda x: x.ordinal)

            hm = HierarchyMetadata(
                name=hname,
                table_name=tname,
                levels=levels,
                is_hidden=h.get("isHidden", False),
            )
            hierarchies.append(hm)
            all_hierarchies.append(hm)

        metadata.tables.append(TableMetadata(
            name=tname,
            is_hidden=table.get("isHidden", False),
            is_technical=is_tech,
            columns=columns,
            measures=measures,
            hierarchies=hierarchies,  # NOVO
            partition_count=len(table.get("partitions", [])),
        ))

    # Hierarquias globais no modelo
    metadata.hierarchies = all_hierarchies

    # ── Relacionamentos ───────────────────────────────────────
    for rel in rels_raw:
        from_card = rel.get("fromCardinality", "many")
        to_card = rel.get("toCardinality", "one")
        metadata.relationships.append(RelationshipMetadata(
            name=rel.get("name", ""),
            from_table=rel.get("fromTable", ""),
            from_column=rel.get("fromColumn", ""),
            to_table=rel.get("toTable", ""),
            to_column=rel.get("toColumn", ""),
            cardinality=f"{from_card}:{to_card}",
            cross_filtering=rel.get("crossFilteringBehavior", "OneDirection"),
            is_active=rel.get("isActive", True),
        ))

    return metadata


# ============================================================================
# Bridge: ModelMetadata -> DependencyGraph
# ============================================================================

def load_model_into_graph(metadata: ModelMetadata):
    """Carrega metadados extraidos no DependencyGraph."""
    from pbi_refactor_agent.discovery.dependency_graph import DependencyGraph
    from pbi_refactor_agent.models import (
        CalculatedColumnInfo,
        ColumnInfo,
        MeasureInfo,
        RelationshipInfo,
        TableInfo,
    )

    graph = DependencyGraph()

    for table in metadata.tables:
        if table.is_technical:
            continue

        col_names = [c.name for c in table.columns]
        measure_names = [m.name for m in table.measures]
        calc_col_names = [c.name for c in table.columns if c.expression]

        graph.add_table(TableInfo(
            name=table.name,
            columns=col_names,
            measures=measure_names,
            calculated_columns=calc_col_names,
            is_hidden=table.is_hidden if hasattr(table, "is_hidden") else False,
        ))

        for col in table.columns:
            if col.expression:
                graph.add_calculated_column(CalculatedColumnInfo(
                    name=col.name,
                    table_name=table.name,
                    data_type=col.data_type,
                    expression=col.expression,
                ))
            else:
                graph.add_column(ColumnInfo(
                    name=col.name,
                    table_name=table.name,
                    data_type=col.data_type,
                    is_hidden=col.is_hidden,
                ))

        for m in table.measures:
            graph.add_measure(MeasureInfo(
                name=m.name,
                table_name=table.name,
                expression=m.expression,
                format_string=m.format_string,
                display_folder=m.display_folder,
            ))

    for rel in metadata.relationships:
        graph.add_relationship(RelationshipInfo(
            name=rel.name or f"{rel.from_table}_{rel.to_table}",
            from_table=rel.from_table,
            from_column=rel.from_column,
            to_table=rel.to_table,
            to_column=rel.to_column,
            is_active=rel.is_active,
            cross_filter_direction=rel.cross_filtering,
        ))

    return graph


# ============================================================================
# Public API
# ============================================================================

def extract_model(file_path: str) -> ModelMetadata:
    path = Path(file_path)
    if not path.exists():
        raise ExtractionError(f"Arquivo nao encontrado: {file_path}")
    suffix = path.suffix.lower()
    if suffix != ".pbit":
        raise ExtractionError(
            f"Formato nao suportado: {suffix}. Use apenas arquivos .pbit."
        )
    return extract_from_pbit(path)


def extract_raw_schema_tables(file_path: str) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        raise ExtractionError(f"Arquivo nao encontrado: {file_path}")
    with zipfile.ZipFile(path, "r") as zf:
        schema_files = [f for f in zf.namelist() if "DataModelSchema" in f or "DataModel" in f]
        if not schema_files:
            return []
        for sf in schema_files:
            try:
                raw = zf.read(sf)
                schema = _parse_json_bytes(raw, sf)
                if "model" in schema:
                    return schema["model"].get("tables", [])
            except Exception:
                continue
    return []


def generate_markdown_report(metadata: ModelMetadata) -> str:
    md = f"# {metadata.file_name} - Modelo de Dados Power BI\n\n"
    md += f"**Tipo:** {metadata.file_type.upper()} | "
    md += f"**Método de extração:** {metadata.extraction_method}\n\n"

    s = metadata.summary
    md += "## Resumo do Modelo\n\n"
    md += f"- **Tabelas de negócio:** {s['business_tables']}\n"
    md += f"- **Tabelas técnicas:** {s['technical_tables']}\n"
    md += f"- **Total de colunas:** {s['total_columns']}\n"
    md += f"- **Total de medidas:** {s['total_measures']}\n"
    md += f"- **Relacionamentos:** {s['total_relationships']}\n"
    md += f"- **Hierarquias:** {s['total_hierarchies']}\n\n"
    md += "---\n\n"

    md += "## Tabelas e Medidas\n\n"
    for table in metadata.business_tables:
        if table.is_hidden and not any(not m.is_hidden for m in table.measures):
            continue

        suffix = " *(oculta)*" if table.is_hidden else ""
        md += f"### {table.name}{suffix}\n\n"

        visible_cols = [c for c in table.columns if not c.is_hidden]
        if visible_cols:
            md += "**Colunas:**\n\n"
            md += "| Coluna | Tipo | Categoria | Ordenação |\n"
            md += "|--------|------|-----------|----------|\n"
            for col in visible_cols:
                label = CATEGORY_LABELS_PT.get(col.category, col.category)
                sort_info = f"`{col.sort_by_column}`" if col.sort_by_column else "—"
                md += f"| `{col.name}` | {col.data_type} | {label} | {sort_info} |\n"
            md += "\n"

        # Hierarquias da tabela
        if table.hierarchies:
            md += "**Hierarquias:**\n\n"
            for h in table.hierarchies:
                levels_str = " → ".join(f"`{lv.column}`" for lv in h.levels)
                md += f"- **{h.name}:** {levels_str}\n"
            md += "\n"

        visible_measures = [m for m in table.measures if not m.is_hidden]
        if visible_measures:
            md += "**Medidas:**\n\n"
            by_cat = {}
            for m in visible_measures:
                by_cat.setdefault(m.category, []).append(m)

            cat_order = [
                "revenue", "cost", "margin", "percentage", "ratio",
                "temporal", "calendar_intelligence", "aggregation",
                "filtering", "other",
            ]
            for cat in cat_order:
                if cat not in by_cat:
                    continue
                label = CATEGORY_LABELS_PT.get(cat, cat)
                md += f"#### {label}\n\n"
                for m in by_cat[cat]:
                    cplx = {"simple": "simples", "medium": "média", "complex": "complexa"}
                    kpi_flag = " 🎯 KPI" if m.kpi else ""
                    md += f"**{m.name}** *({cplx.get(m.complexity, m.complexity)})*{kpi_flag}\n\n"
                    if m.display_folder:
                        md += f"*Pasta:* `{m.display_folder}`\n\n"
                    if m.description:
                        md += f"*Descrição:* {m.description}\n\n"
                    if m.formatted_expression:
                        md += f"```dax\n{m.formatted_expression}\n```\n\n"
                    if m.format_string:
                        md += f"*Formato:* `{m.format_string}`\n\n"
                    md += "---\n\n"
        md += "\n"

    if metadata.relationships:
        md += "## Relacionamentos\n\n"
        md += "| De | Para | Cardinalidade | Direção |\n"
        md += "|----|------|---------------|----------|\n"
        for r in metadata.relationships:
            f_str = f"{r.from_table}.{r.from_column}"
            t_str = f"{r.to_table}.{r.to_column}"
            md += f"| {f_str} | {t_str} | {r.cardinality} | {r.cross_filtering} |\n"
        md += "\n"

    if metadata.hierarchies:
        md += "## Hierarquias\n\n"
        md += "| Tabela | Hierarquia | Níveis |\n"
        md += "|--------|------------|--------|\n"
        for h in metadata.hierarchies:
            levels_str = " → ".join(lv.column for lv in h.levels)
            md += f"| {h.table_name} | {h.name} | {levels_str} |\n"
        md += "\n"

    return md


# ============================================================================
# Write-back: Salvar .pbit refatorado
# ============================================================================

def save_refactored_pbit(
    original_path: str,
    refactored_items: list,
    output_path: Optional[str] = None,
) -> str:
    src = Path(original_path)
    if not src.exists():
        raise ExtractionError(f"Arquivo original nao encontrado: {original_path}")

    if output_path is None:
        output_path = str(src.with_stem(src.stem + "_refactored"))

    with zipfile.ZipFile(src, "r") as zf_in:
        all_entries = {name: zf_in.read(name) for name in zf_in.namelist()}

    schema_name = next(
        (n for n in all_entries if "DataModelSchema" in n or "DataModel" in n),
        None,
    )
    if schema_name is None:
        raise ExtractionError("DataModelSchema nao encontrado no .pbit")

    raw_bytes = all_entries[schema_name]

    original_encoding = "utf-16-le"
    for enc in ("utf-16-le", "utf-8", "utf-16", "latin-1"):
        try:
            raw_bytes.decode(enc)
            original_encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    schema = _parse_json_bytes(raw_bytes, schema_name)

    changes_applied = 0
    schema_table_names = [t.get("name") for t in schema.get("model", {}).get("tables", [])]

    for item in refactored_items:
        if not getattr(item, "refactored_expression", None):
            continue

        obj = item.object
        obj_name = obj.name
        obj_table = getattr(obj, "table_name", None)

        for table in schema.get("model", {}).get("tables", []):
            if obj_table and table.get("name") != obj_table:
                continue
            for measure in table.get("measures", []):
                if measure.get("name") == obj_name:
                    expr = item.refactored_expression
                    existing = measure.get("expression")
                    if isinstance(existing, list):
                        measure["expression"] = expr.split("\n")
                    else:
                        measure["expression"] = expr
                    changes_applied += 1
                    break
            for col in table.get("columns", []):
                if col.get("name") == obj_name and col.get("expression"):
                    expr = item.refactored_expression
                    existing = col.get("expression")
                    if isinstance(existing, list):
                        col["expression"] = expr.split("\n")
                    else:
                        col["expression"] = expr
                    changes_applied += 1
                    break

    if changes_applied == 0:
        item_details = [
            f"{getattr(i.object, 'table_name', '?')}.{i.object.name}"
            for i in refactored_items
            if getattr(i, "refactored_expression", None)
        ]
        raise ExtractionError(
            f"Nenhuma expressão foi aplicada ao schema. "
            f"Items: {item_details}. "
            f"Schema tables: {schema_table_names}"
        )

    new_json = json.dumps(schema, ensure_ascii=False, indent=2)
    new_bytes = new_json.encode(original_encoding)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf_out:
        for name, data in all_entries.items():
            if name == schema_name:
                zf_out.writestr(name, new_bytes)
            else:
                zf_out.writestr(name, data)

    return str(out)