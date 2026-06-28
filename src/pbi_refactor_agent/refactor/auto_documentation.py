"""
Documentacao Automatica de Medidas com LLM.

Usa LLM para gerar descricoes em linguagem natural (portugues)
para cada medida DAX do modelo, facilitando o entendimento
por analistas de negocio.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import structlog

from pbi_refactor_agent.config import LLMProvider, Settings, get_settings
from pbi_refactor_agent.refactor.llm_client import LLMClient

logger = structlog.get_logger(__name__)


SYSTEM_PROMPT = """Voce e um especialista em Power BI e DAX.
Sua tarefa e gerar descricoes claras e concisas em portugues
para medidas DAX, de modo que um analista de negocio (nao tecnico) entenda.

REGRAS:
1. Use linguagem simples e direta
2. Explique O QUE a medida calcula, nao COMO
3. Maximo 2 frases
4. Nao repita o nome da medida na descricao
5. Se a medida usa time intelligence, mencione o periodo

FORMATO: Retorne APENAS a descricao, sem formatacao extra.
"""

MEASURE_PROMPT = """Medida: {measure_name}
Tabela: {table_name}
Expressao DAX:
```
{expression}
```
{format_info}
Gere uma descricao curta em portugues."""


@dataclass
class MeasureDocumentation:
    """Documentacao gerada para uma medida."""
    measure_name: str
    table_name: str
    expression: str
    description: str
    generated: bool = True


@dataclass
class DocumentationResult:
    """Resultado da documentacao automatica."""
    items: list[MeasureDocumentation] = field(default_factory=list)
    total_measures: int = 0
    documented: int = 0
    failed: int = 0
    duration_seconds: float = 0.0

    @property
    def coverage(self) -> float:
        if self.total_measures == 0:
            return 0.0
        return self.documented / self.total_measures


class AutoDocumentor:
    """
    Gera documentacao automatica para medidas DAX usando LLM.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()

    async def document_measures(
        self,
        metadata,
        llm_provider: Optional[LLMProvider] = None,
        llm_model: Optional[str] = None,
        max_measures: int = 50,
        progress_callback=None,
    ) -> DocumentationResult:
        """
        Gera descricoes para todas as medidas visiveis do modelo.

        Args:
            metadata: ModelMetadata extraido do .pbit.
            llm_provider: Provedor LLM.
            llm_model: Modelo LLM.
            max_measures: Limite de medidas a documentar.
            progress_callback: Funcao chamada com (current, total).

        Returns:
            DocumentationResult com todas as descricoes.
        """
        import time
        start = time.perf_counter()

        provider = llm_provider or self._settings.default_llm_provider

        client = LLMClient(
            provider=provider,
            model=llm_model,
            settings=self._settings,
        )

        # Coletar medidas
        measures_to_doc = []
        for table in metadata.business_tables:
            for m in table.measures:
                if not m.is_hidden and m.expression:
                    measures_to_doc.append((table.name, m))

        result = DocumentationResult(total_measures=len(measures_to_doc))

        # Limitar
        measures_to_doc = measures_to_doc[:max_measures]

        for i, (tname, measure) in enumerate(measures_to_doc):
            if progress_callback:
                progress_callback(i + 1, len(measures_to_doc))

            try:
                format_info = ""
                if measure.format_string:
                    format_info = f"Formato: {measure.format_string}"

                prompt = MEASURE_PROMPT.format(
                    measure_name=measure.name,
                    table_name=tname,
                    expression=measure.expression[:500],
                    format_info=format_info,
                )

                description = await client.complete(
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_tokens=200,
                )

                # Limpar resposta
                description = description.strip().strip('"').strip("'")

                result.items.append(MeasureDocumentation(
                    measure_name=measure.name,
                    table_name=tname,
                    expression=measure.expression,
                    description=description,
                    generated=True,
                ))
                result.documented += 1

            except Exception as e:
                logger.warning(
                    "Falha ao documentar medida",
                    measure=measure.name,
                    error=str(e),
                )
                result.items.append(MeasureDocumentation(
                    measure_name=measure.name,
                    table_name=tname,
                    expression=measure.expression,
                    description=f"Erro: {str(e)[:80]}",
                    generated=False,
                ))
                result.failed += 1

        result.duration_seconds = round(time.perf_counter() - start, 2)

        logger.info(
            "Documentacao automatica concluida",
            documented=result.documented,
            failed=result.failed,
            duration=result.duration_seconds,
        )
        return result

    def export_markdown(self, result: DocumentationResult) -> str:
        """Exporta documentacao como Markdown."""
        md = "# Documentacao de Medidas (Gerada por IA)\n\n"

        by_table = {}
        for item in result.items:
            by_table.setdefault(item.table_name, []).append(item)

        for tname in sorted(by_table):
            md += f"## {tname}\n\n"
            md += "| Medida | Descricao |\n"
            md += "|--------|-----------|\n"
            for item in by_table[tname]:
                desc = item.description.replace("|", "\\|").replace("\n", " ")
                md += f"| `{item.measure_name}` | {desc} |\n"
            md += "\n"

        md += f"\n---\n*{result.documented} medidas documentadas automaticamente*\n"
        return md
