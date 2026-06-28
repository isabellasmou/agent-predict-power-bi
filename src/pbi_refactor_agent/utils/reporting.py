"""
Geração de Relatórios.

Gera relatórios detalhados das operações de refatoração
em diferentes formatos (texto, JSON, HTML, Markdown).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import structlog

from pbi_refactor_agent.models import (
    ImpactAnalysis,
    RefactorResult,
    RefactorStatus,
    ValidationStatus,
)

logger = structlog.get_logger(__name__)


class ReportGenerator:
    """
    Gerador de relatórios de refatoração.
    
    Produz relatórios detalhados em múltiplos formatos.
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Inicializa o gerador.
        
        Args:
            output_dir: Diretório para salvar relatórios.
        """
        self._output_dir = output_dir or Path("reports")
        self._output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_impact_report(
        self,
        analysis: ImpactAnalysis,
        format: str = "text"
    ) -> str:
        """
        Gera relatório de análise de impacto.
        
        Args:
            analysis: Análise de impacto.
            format: Formato do relatório (text, json, markdown).
            
        Returns:
            Relatório gerado.
        """
        if format == "json":
            return self._impact_report_json(analysis)
        elif format == "markdown":
            return self._impact_report_markdown(analysis)
        else:
            return self._impact_report_text(analysis)
    
    def generate_refactor_report(
        self,
        result: RefactorResult,
        format: str = "text"
    ) -> str:
        """
        Gera relatório de resultado de refatoração.
        
        Args:
            result: Resultado da refatoração.
            format: Formato do relatório (text, json, markdown).
            
        Returns:
            Relatório gerado.
        """
        if format == "json":
            return self._refactor_report_json(result)
        elif format == "markdown":
            return self._refactor_report_markdown(result)
        else:
            return self._refactor_report_text(result)
    
    def save_report(
        self,
        content: str,
        name: str,
        format: str = "txt"
    ) -> Path:
        """
        Salva relatório em arquivo.
        
        Args:
            content: Conteúdo do relatório.
            name: Nome base do arquivo.
            format: Extensão do arquivo.
            
        Returns:
            Caminho do arquivo salvo.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.{format}"
        filepath = self._output_dir / filename
        
        filepath.write_text(content, encoding="utf-8")
        
        logger.info("Relatório salvo", path=str(filepath))
        return filepath
    
    def _impact_report_text(self, analysis: ImpactAnalysis) -> str:
        """Gera relatório de impacto em texto."""
        lines = [
            "=" * 60,
            "RELATÓRIO DE ANÁLISE DE IMPACTO",
            "=" * 60,
            "",
            f"Data: {analysis.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Tipo de Mudança: {analysis.change_type.value}",
            f"Objeto Alvo: {analysis.target_object.full_name}",
            f"Novo Valor: {analysis.new_value or 'N/A'}",
            "",
            "-" * 40,
            "RESUMO",
            "-" * 40,
            f"Total de Objetos Impactados: {analysis.total_impacted}",
            f"  - Impactos Diretos: {len(analysis.direct_impacts)}",
            f"  - Impactos em Cascata: {len(analysis.cascade_impacts)}",
            f"  - Relacionamentos: {len(analysis.relationship_impacts)}",
            f"Requer Revisão Manual: {'Sim' if analysis.requires_manual_review else 'Não'}",
            "",
        ]
        
        # Impactos diretos
        if analysis.direct_impacts:
            lines.extend([
                "-" * 40,
                "IMPACTOS DIRETOS",
                "-" * 40,
            ])
            
            for i, impact in enumerate(analysis.direct_impacts, 1):
                lines.extend([
                    f"\n{i}. {impact.object.full_name}",
                    f"   Tipo: {impact.object.object_type.value}",
                    f"   Revisão Manual: {'Sim' if impact.requires_manual_review else 'Não'}",
                ])
                
                if impact.notes:
                    lines.append(f"   Notas: {impact.notes}")
        
        # Impactos em cascata
        if analysis.cascade_impacts:
            lines.extend([
                "",
                "-" * 40,
                "IMPACTOS EM CASCATA",
                "-" * 40,
            ])
            
            for i, impact in enumerate(analysis.cascade_impacts, 1):
                lines.extend([
                    f"\n{i}. {impact.object.full_name}",
                    f"   Tipo: {impact.object.object_type.value}",
                ])
        
        # Relacionamentos
        if analysis.relationship_impacts:
            lines.extend([
                "",
                "-" * 40,
                "RELACIONAMENTOS IMPACTADOS",
                "-" * 40,
            ])
            
            for i, rel in enumerate(analysis.relationship_impacts, 1):
                lines.append(f"{i}. {rel.full_name}")
        
        lines.extend(["", "=" * 60])
        
        return "\n".join(lines)
    
    def _impact_report_json(self, analysis: ImpactAnalysis) -> str:
        """Gera relatório de impacto em JSON."""
        data = {
            "timestamp": analysis.timestamp.isoformat(),
            "change_type": analysis.change_type.value,
            "target_object": {
                "name": analysis.target_object.name,
                "type": analysis.target_object.object_type.value,
                "table": analysis.target_object.table_name,
            },
            "new_value": analysis.new_value,
            "summary": {
                "total_impacted": analysis.total_impacted,
                "direct_impacts": len(analysis.direct_impacts),
                "cascade_impacts": len(analysis.cascade_impacts),
                "relationship_impacts": len(analysis.relationship_impacts),
                "requires_manual_review": analysis.requires_manual_review,
            },
            "direct_impacts": [
                {
                    "object": impact.object.full_name,
                    "type": impact.object.object_type.value,
                    "requires_manual_review": impact.requires_manual_review,
                    "notes": impact.notes,
                }
                for impact in analysis.direct_impacts
            ],
            "cascade_impacts": [
                {
                    "object": impact.object.full_name,
                    "type": impact.object.object_type.value,
                }
                for impact in analysis.cascade_impacts
            ],
            "relationship_impacts": [
                {
                    "name": rel.name,
                    "from": f"{rel.from_table}[{rel.from_column}]",
                    "to": f"{rel.to_table}[{rel.to_column}]",
                }
                for rel in analysis.relationship_impacts
            ],
        }
        
        return json.dumps(data, indent=2, ensure_ascii=False)
    
    def _impact_report_markdown(self, analysis: ImpactAnalysis) -> str:
        """Gera relatório de impacto em Markdown."""
        lines = [
            "# Relatório de Análise de Impacto",
            "",
            f"**Data:** {analysis.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Mudança Proposta",
            "",
            f"- **Tipo:** {analysis.change_type.value}",
            f"- **Objeto:** `{analysis.target_object.full_name}`",
            f"- **Novo Valor:** {analysis.new_value or 'N/A'}",
            "",
            "## Resumo",
            "",
            f"| Métrica | Valor |",
            f"|---------|-------|",
            f"| Total Impactado | {analysis.total_impacted} |",
            f"| Impactos Diretos | {len(analysis.direct_impacts)} |",
            f"| Impactos Cascata | {len(analysis.cascade_impacts)} |",
            f"| Relacionamentos | {len(analysis.relationship_impacts)} |",
            f"| Revisão Manual | {'✅ Sim' if analysis.requires_manual_review else '❌ Não'} |",
            "",
        ]
        
        # Impactos diretos
        if analysis.direct_impacts:
            lines.extend([
                "## Impactos Diretos",
                "",
                "| Objeto | Tipo | Revisão Manual |",
                "|--------|------|----------------|",
            ])
            
            for impact in analysis.direct_impacts:
                manual = "⚠️" if impact.requires_manual_review else "✓"
                lines.append(
                    f"| `{impact.object.full_name}` | {impact.object.object_type.value} | {manual} |"
                )
            
            lines.append("")
        
        # Impactos em cascata
        if analysis.cascade_impacts:
            lines.extend([
                "## Impactos em Cascata",
                "",
                "| Objeto | Tipo |",
                "|--------|------|",
            ])
            
            for impact in analysis.cascade_impacts:
                lines.append(
                    f"| `{impact.object.full_name}` | {impact.object.object_type.value} |"
                )
            
            lines.append("")
        
        # Relacionamentos
        if analysis.relationship_impacts:
            lines.extend([
                "## Relacionamentos Impactados",
                "",
                "| De | Para |",
                "|----|------|",
            ])
            
            for rel in analysis.relationship_impacts:
                lines.append(
                    f"| `{rel.from_table}[{rel.from_column}]` | `{rel.to_table}[{rel.to_column}]` |"
                )
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _refactor_report_text(self, result: RefactorResult) -> str:
        """Gera relatório de refatoração em texto."""
        lines = [
            "=" * 60,
            "RELATÓRIO DE REFATORAÇÃO",
            "=" * 60,
            "",
            f"Status: {result.status.value.upper()}",
            f"Início: {result.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        
        if result.end_time:
            lines.append(f"Fim: {result.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if result.duration_seconds:
            lines.append(f"Duração: {result.duration_seconds:.2f}s")
        
        lines.extend([
            "",
            "-" * 40,
            "ESTATÍSTICAS",
            "-" * 40,
            f"Total de Itens: {result.total_items}",
            f"  - Sucesso: {result.successful_items}",
            f"  - Falha: {result.failed_items}",
            f"  - Ignorados: {result.skipped_items}",
            "",
            f"Aplicado: {'Sim' if result.applied else 'Não'}",
        ])
        
        if result.rolled_back:
            lines.append("Revertido: Sim")
        
        if result.error_message:
            lines.extend([
                "",
                "-" * 40,
                "ERRO",
                "-" * 40,
                result.error_message,
            ])
        
        # Detalhes dos itens
        lines.extend([
            "",
            "-" * 40,
            "ITENS REFATORADOS",
            "-" * 40,
        ])
        
        for i, item in enumerate(result.items, 1):
            status_icon = "✓" if item.is_validated else "✗"
            lines.extend([
                f"\n{i}. [{status_icon}] {item.object.full_name}",
                f"   LLM: {item.llm_provider}/{item.llm_model}",
                f"   Confiança: {item.confidence_score:.1%}",
            ])
            
            if item.validation:
                lines.append(f"   Validação: {item.validation.status.value}")
                
                if item.validation.error_message:
                    lines.append(f"   Erro: {item.validation.error_message}")
        
        lines.extend(["", "=" * 60])
        
        return "\n".join(lines)
    
    def _refactor_report_json(self, result: RefactorResult) -> str:
        """Gera relatório de refatoração em JSON."""
        data = {
            "status": result.status.value,
            "start_time": result.start_time.isoformat(),
            "end_time": result.end_time.isoformat() if result.end_time else None,
            "duration_seconds": result.duration_seconds,
            "statistics": {
                "total": result.total_items,
                "successful": result.successful_items,
                "failed": result.failed_items,
                "skipped": result.skipped_items,
            },
            "applied": result.applied,
            "rolled_back": result.rolled_back,
            "error_message": result.error_message,
            "items": [
                {
                    "object": item.object.full_name,
                    "type": item.object.object_type.value,
                    "llm_provider": item.llm_provider,
                    "llm_model": item.llm_model,
                    "confidence_score": item.confidence_score,
                    "validated": item.is_validated,
                    "applied": item.applied,
                    "validation_status": item.validation.status.value if item.validation else None,
                }
                for item in result.items
            ],
        }
        
        return json.dumps(data, indent=2, ensure_ascii=False)
    
    def _refactor_report_markdown(self, result: RefactorResult) -> str:
        """Gera relatório de refatoração em Markdown."""
        status_emoji = {
            RefactorStatus.COMPLETED: "✅",
            RefactorStatus.FAILED: "❌",
            RefactorStatus.IN_PROGRESS: "🔄",
            RefactorStatus.PENDING: "⏳",
            RefactorStatus.ROLLED_BACK: "↩️",
        }
        
        lines = [
            "# Relatório de Refatoração",
            "",
            f"**Status:** {status_emoji.get(result.status, '')} {result.status.value}",
            f"**Início:** {result.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        
        if result.duration_seconds:
            lines.append(f"**Duração:** {result.duration_seconds:.2f}s")
        
        lines.extend([
            "",
            "## Estatísticas",
            "",
            "| Métrica | Valor |",
            "|---------|-------|",
            f"| Total | {result.total_items} |",
            f"| Sucesso | {result.successful_items} |",
            f"| Falha | {result.failed_items} |",
            f"| Ignorados | {result.skipped_items} |",
            f"| Aplicado | {'Sim' if result.applied else 'Não'} |",
            "",
        ])
        
        if result.error_message:
            lines.extend([
                "## ⚠️ Erro",
                "",
                f"> {result.error_message}",
                "",
            ])
        
        # Itens
        lines.extend([
            "## Itens Refatorados",
            "",
            "| Objeto | LLM | Confiança | Status |",
            "|--------|-----|-----------|--------|",
        ])
        
        for item in result.items:
            status = "✓" if item.is_validated else "✗"
            lines.append(
                f"| `{item.object.full_name}` | {item.llm_model} | {item.confidence_score:.0%} | {status} |"
            )
        
        return "\n".join(lines)
