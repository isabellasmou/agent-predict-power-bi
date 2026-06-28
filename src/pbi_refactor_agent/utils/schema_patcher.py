"""
Schema Patcher para modelos Power BI (.pbit).

Aplica renomeios estruturais diretamente no DataModelSchema JSON:
- Renomear coluna: atualiza nome, relacionamentos, hierarquias, sortByColumn
- Renomear tabela: atualiza nome, relacionamentos
- Renomear medida: atualiza nome, KPIs

As expressões DAX (medidas e colunas calculadas) são tratadas
separadamente pelo LLM + save_refactored_pbit.
"""

import json
import zipfile
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class SchemaPatcher:
    """
    Aplica renomeios estruturais no DataModelSchema de um .pbit.

    Responsável por atualizar todos os metadados do schema que
    NÃO são expressões DAX (essas ficam com o LLM).
    """

    def patch_rename_column(
        self,
        schema: dict,
        table_name: str,
        old_column: str,
        new_column: str,
    ) -> dict:
        """
        Renomeia uma coluna em todos os lugares do schema.

        Atualiza:
        - Nome da coluna na tabela
        - sourceColumn (se igual ao nome antigo)
        - Relacionamentos (fromColumn / toColumn)
        - Hierarquias (levels[].column)
        - sortByColumn de outras colunas que dependem desta
        """
        model = schema.get("model", {})
        changes = []

        for table in model.get("tables", []):
            if table.get("name", "").lower() != table_name.lower():
                continue

            # ── Nome da coluna ────────────────────────────────
            for col in table.get("columns", []):
                if col.get("name", "").lower() == old_column.lower():
                    col["name"] = new_column
                    changes.append(f"column name: {old_column} → {new_column}")

                    # sourceColumn — só atualiza se for igual ao nome antigo
                    # (colunas calculadas não têm sourceColumn)
                    if col.get("sourceColumn", "").lower() == old_column.lower():
                        col["sourceColumn"] = new_column
                        changes.append(f"sourceColumn: {old_column} → {new_column}")

            # ── sortByColumn de outras colunas ────────────────
            for col in table.get("columns", []):
                if col.get("sortByColumn", "").lower() == old_column.lower():
                    col["sortByColumn"] = new_column
                    changes.append(
                        f"sortByColumn em '{col.get('name')}': {old_column} → {new_column}"
                    )

            # ── Hierarquias ───────────────────────────────────
            for hierarchy in table.get("hierarchies", []):
                for level in hierarchy.get("levels", []):
                    if level.get("column", "").lower() == old_column.lower():
                        level["column"] = new_column
                        changes.append(
                            f"hierarchy '{hierarchy.get('name')}' level "
                            f"'{level.get('name')}': {old_column} → {new_column}"
                        )

        # ── Relacionamentos ───────────────────────────────────
        for rel in model.get("relationships", []):
            if (
                rel.get("fromTable", "").lower() == table_name.lower()
                and rel.get("fromColumn", "").lower() == old_column.lower()
            ):
                rel["fromColumn"] = new_column
                changes.append(
                    f"relationship fromColumn ({rel.get('fromTable')}): "
                    f"{old_column} → {new_column}"
                )

            if (
                rel.get("toTable", "").lower() == table_name.lower()
                and rel.get("toColumn", "").lower() == old_column.lower()
            ):
                rel["toColumn"] = new_column
                changes.append(
                    f"relationship toColumn ({rel.get('toTable')}): "
                    f"{old_column} → {new_column}"
                )

        logger.info(
            "patch_rename_column concluído",
            table=table_name,
            old=old_column,
            new=new_column,
            changes=len(changes),
        )

        for c in changes:
            logger.debug("schema_change", detail=c)

        return schema

    def patch_rename_table(
        self,
        schema: dict,
        old_table: str,
        new_table: str,
    ) -> dict:
        """
        Renomeia uma tabela em todos os lugares do schema.

        Atualiza:
        - Nome da tabela
        - Relacionamentos (fromTable / toTable)
        """
        model = schema.get("model", {})
        changes = []

        # ── Nome da tabela ────────────────────────────────────
        for table in model.get("tables", []):
            if table.get("name", "").lower() == old_table.lower():
                table["name"] = new_table
                changes.append(f"table name: {old_table} → {new_table}")

        # ── Relacionamentos ───────────────────────────────────
        for rel in model.get("relationships", []):
            if rel.get("fromTable", "").lower() == old_table.lower():
                rel["fromTable"] = new_table
                changes.append(f"relationship fromTable: {old_table} → {new_table}")

            if rel.get("toTable", "").lower() == old_table.lower():
                rel["toTable"] = new_table
                changes.append(f"relationship toTable: {old_table} → {new_table}")

        logger.info(
            "patch_rename_table concluído",
            old=old_table,
            new=new_table,
            changes=len(changes),
        )

        return schema

    def patch_rename_measure(
        self,
        schema: dict,
        table_name: str,
        old_measure: str,
        new_measure: str,
    ) -> dict:
        """
        Renomeia uma medida em todos os lugares do schema.

        Atualiza:
        - Nome da medida
        - KPI targetMeasure (se referencia a medida renomeada)
        """
        model = schema.get("model", {})
        changes = []

        for table in model.get("tables", []):
            for measure in table.get("measures", []):

                # ── Nome da medida ────────────────────────────
                if (
                    table.get("name", "").lower() == table_name.lower()
                    and measure.get("name", "").lower() == old_measure.lower()
                ):
                    measure["name"] = new_measure
                    changes.append(f"measure name: {old_measure} → {new_measure}")

                # ── KPI targetMeasure ─────────────────────────
                kpi = measure.get("kpi")
                if kpi and kpi.get("targetMeasure", "").lower() == old_measure.lower():
                    kpi["targetMeasure"] = new_measure
                    changes.append(
                        f"KPI targetMeasure em '{measure.get('name')}': "
                        f"{old_measure} → {new_measure}"
                    )

        logger.info(
            "patch_rename_measure concluído",
            table=table_name,
            old=old_measure,
            new=new_measure,
            changes=len(changes),
        )

        return schema


def apply_structural_rename(
    original_path: str,
    change_type: str,
    table_name: Optional[str],
    old_name: str,
    new_name: str,
    refactored_items: Optional[list] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Função principal: aplica renomeio estrutural + expressões DAX refatoradas
    e salva um novo .pbit completo e válido.

    Args:
        original_path: Caminho do .pbit original.
        change_type: "rename_column", "rename_table" ou "rename_measure".
        table_name: Nome da tabela (para rename_column e rename_measure).
        old_name: Nome antigo do objeto.
        new_name: Nome novo do objeto.
        refactored_items: Lista de RefactorItem com expressões DAX refatoradas
                          pelo LLM (opcional — se None, só aplica o renomeio).
        output_path: Caminho de saída (default: <original>_refactored.pbit).

    Returns:
        Caminho do arquivo .pbit gerado.
    """
    from pbi_refactor_agent.utils.pbix_extractor import (
        ExtractionError,
        _parse_json_bytes,
    )

    src = Path(original_path)
    if not src.exists():
        raise ExtractionError(f"Arquivo não encontrado: {original_path}")

    if output_path is None:
        output_path = str(src.with_stem(src.stem + "_refactored"))

    # ── Ler ZIP original ──────────────────────────────────────
    with zipfile.ZipFile(src, "r") as zf_in:
        all_entries = {name: zf_in.read(name) for name in zf_in.namelist()}

    schema_name = next(
        (n for n in all_entries if "DataModelSchema" in n or "DataModel" in n),
        None,
    )
    if schema_name is None:
        raise ExtractionError("DataModelSchema não encontrado no .pbit")

    raw_bytes = all_entries[schema_name]

    # Detectar encoding original
    original_encoding = "utf-16-le"
    for enc in ("utf-16-le", "utf-8", "utf-16", "latin-1"):
        try:
            raw_bytes.decode(enc)
            original_encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    schema = _parse_json_bytes(raw_bytes, schema_name)

    # ── 1. Aplicar renomeio estrutural ────────────────────────
    patcher = SchemaPatcher()

    if change_type == "rename_column":
        if not table_name:
            raise ValueError("table_name é obrigatório para rename_column")
        schema = patcher.patch_rename_column(schema, table_name, old_name, new_name)

    elif change_type == "rename_table":
        schema = patcher.patch_rename_table(schema, old_name, new_name)

    elif change_type == "rename_measure":
        if not table_name:
            raise ValueError("table_name é obrigatório para rename_measure")
        schema = patcher.patch_rename_measure(schema, table_name, old_name, new_name)

    else:
        raise ValueError(f"change_type não suportado: {change_type}")

    # ── 2. Aplicar expressões DAX refatoradas pelo LLM ────────
    dax_changes = 0
    if refactored_items:
        for item in refactored_items:
            if not getattr(item, "refactored_expression", None):
                continue

            obj = item.object
            obj_name = obj.name
            obj_table = getattr(obj, "table_name", None)

            for table in schema.get("model", {}).get("tables", []):
                if obj_table and table.get("name", "").lower() != obj_table.lower():
                    continue

                for measure in table.get("measures", []):
                    if measure.get("name", "").lower() == obj_name.lower():
                        expr = item.refactored_expression
                        existing = measure.get("expression")
                        measure["expression"] = (
                            expr.split("\n") if isinstance(existing, list) else expr
                        )
                        dax_changes += 1
                        break

                for col in table.get("columns", []):
                    if col.get("name", "").lower() == obj_name.lower() and col.get("expression"):
                        expr = item.refactored_expression
                        existing = col.get("expression")
                        col["expression"] = (
                            expr.split("\n") if isinstance(existing, list) else expr
                        )
                        dax_changes += 1
                        break

    logger.info(
        "apply_structural_rename concluído",
        change_type=change_type,
        old=old_name,
        new=new_name,
        dax_changes=dax_changes,
    )

    # ── 3. Serializar e salvar ────────────────────────────────
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

    logger.info("pbit gerado", path=str(out))
    return str(out)