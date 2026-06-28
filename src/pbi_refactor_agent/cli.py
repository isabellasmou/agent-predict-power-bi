"""
Interface de linha de comando para o agente de refatoração Power BI.

Usage:
    python -m pbi_refactor_agent.cli analyze --model path/to/model.bim --change "rename column Sales.Amount to TotalAmount"
    python -m pbi_refactor_agent.cli refactor --model path/to/model.bim --change "rename column Sales.Amount to TotalAmount"
    python -m pbi_refactor_agent.cli interactive --model path/to/model.bim
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.syntax import Syntax

from .agent import RefactorAgent
from .config import get_settings
from .models import ChangeType, ProposedChange
from .utils.logging import setup_logging
from .utils.reporting import ReportGenerator


console = Console()


def parse_change_description(description: str) -> Optional[ProposedChange]:
    """
    Parseia uma descrição de mudança em linguagem natural.
    
    Formatos suportados:
    - "rename column {table}.{column} to {new_name}"
    - "rename table {table} to {new_name}"
    - "delete column {table}.{column}"
    - "change datatype {table}.{column} to {new_type}"
    
    Args:
        description: Descrição da mudança em texto
        
    Returns:
        ProposedChange ou None se não conseguir parsear
    """
    description = description.lower().strip()
    
    # Rename column
    if description.startswith("rename column"):
        parts = description.replace("rename column", "").strip().split(" to ")
        if len(parts) == 2:
            source, new_name = parts
            if "." in source:
                table, column = source.split(".", 1)
                return ProposedChange(
                    change_type=ChangeType.RENAME_COLUMN,
                    table_name=table.strip(),
                    object_name=column.strip(),
                    new_value=new_name.strip()
                )
    
    # Rename table
    if description.startswith("rename table"):
        parts = description.replace("rename table", "").strip().split(" to ")
        if len(parts) == 2:
            old_name, new_name = parts
            return ProposedChange(
                change_type=ChangeType.RENAME_TABLE,
                table_name=old_name.strip(),
                object_name=old_name.strip(),
                new_value=new_name.strip()
            )
    
    # Delete column
    if description.startswith("delete column"):
        source = description.replace("delete column", "").strip()
        if "." in source:
            table, column = source.split(".", 1)
            return ProposedChange(
                change_type=ChangeType.DELETE_COLUMN,
                table_name=table.strip(),
                object_name=column.strip()
            )
    
    # Change data type
    if description.startswith("change datatype") or description.startswith("change type"):
        prefix = "change datatype" if "datatype" in description else "change type"
        parts = description.replace(prefix, "").strip().split(" to ")
        if len(parts) == 2:
            source, new_type = parts
            if "." in source:
                table, column = source.split(".", 1)
                return ProposedChange(
                    change_type=ChangeType.CHANGE_DATA_TYPE,
                    table_name=table.strip(),
                    object_name=column.strip(),
                    new_value=new_type.strip()
                )
    
    return None


async def cmd_analyze(args):
    """Comando para analisar impacto de uma mudança."""
    settings = get_settings()
    setup_logging(settings.log_level)
    
    console.print(Panel.fit("🔍 [bold blue]Análise de Impacto[/bold blue]"))
    
    # Parseia a mudança
    change = parse_change_description(args.change)
    if not change:
        console.print("[red]❌ Não foi possível interpretar a mudança.[/red]")
        console.print("Formatos aceitos:")
        console.print("  - rename column {table}.{column} to {new_name}")
        console.print("  - rename table {table} to {new_name}")
        console.print("  - delete column {table}.{column}")
        return 1
    
    console.print(f"\n📋 Mudança identificada:")
    console.print(f"   Tipo: [cyan]{change.change_type.value}[/cyan]")
    console.print(f"   Tabela: [yellow]{change.table_name}[/yellow]")
    console.print(f"   Objeto: [yellow]{change.object_name}[/yellow]")
    if change.new_value:
        console.print(f"   Novo valor: [green]{change.new_value}[/green]")
    
    # Cria agente e analisa
    agent = RefactorAgent(mcp_path=args.mcp_path)
    
    try:
        await agent.connect()
        await agent.discover_model(args.model)
        
        impact = agent.analyze_impact(change)
        
        # Exibe resultados
        console.print(f"\n📊 [bold]Resultado da Análise:[/bold]")
        console.print(f"   Impactos diretos: [red]{len(impact.direct_impacts)}[/red]")
        console.print(f"   Impactos transitivos: [orange1]{len(impact.transitive_impacts)}[/orange1]")
        console.print(f"   Total: [bold]{impact.total_impacted}[/bold]")
        
        if impact.direct_impacts:
            table = Table(title="Objetos Impactados Diretamente")
            table.add_column("Objeto", style="cyan")
            table.add_column("Tipo", style="yellow")
            table.add_column("Expressão Atual", style="white")
            
            for di in impact.direct_impacts[:10]:  # Limita a 10
                table.add_row(
                    di.object.name,
                    di.object.object_type.value if hasattr(di.object, 'object_type') else "unknown",
                    di.original_expression[:50] + "..." if len(di.original_expression or "") > 50 else di.original_expression or ""
                )
            
            console.print(table)
        
        # Salva relatório se solicitado
        if args.output:
            reporter = ReportGenerator()
            report = reporter.generate_impact_report(impact)
            Path(args.output).write_text(report)
            console.print(f"\n✅ Relatório salvo em: [bold]{args.output}[/bold]")
        
        return 0
        
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        return 1
    finally:
        await agent.disconnect()


async def cmd_refactor(args):
    """Comando para executar refatoração."""
    settings = get_settings()
    setup_logging(settings.log_level)
    
    console.print(Panel.fit("🔧 [bold green]Refatoração Automática[/bold green]"))
    
    # Parseia a mudança
    change = parse_change_description(args.change)
    if not change:
        console.print("[red]❌ Não foi possível interpretar a mudança.[/red]")
        return 1
    
    agent = RefactorAgent(mcp_path=args.mcp_path)
    
    try:
        await agent.connect()
        await agent.discover_model(args.model)
        
        # Analisa impacto primeiro
        impact = agent.analyze_impact(change)
        console.print(f"\n📊 {impact.total_impacted} objetos serão afetados.")
        
        if not args.yes:
            if not Confirm.ask("Deseja continuar com a refatoração?"):
                console.print("[yellow]Operação cancelada.[/yellow]")
                return 0
        
        # Executa refatoração
        console.print("\n🔄 Refatorando expressões com LLM...")
        results = await agent.refactor_impact(impact)
        
        # Mostra resultados
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        
        console.print(f"\n📈 Resultados:")
        console.print(f"   ✅ Sucessos: [green]{success_count}[/green]")
        console.print(f"   ❌ Falhas: [red]{fail_count}[/red]")
        
        if args.output:
            reporter = ReportGenerator()
            report = reporter.generate_full_report(impact, results)
            Path(args.output).write_text(report)
            console.print(f"\n✅ Relatório salvo em: [bold]{args.output}[/bold]")
        
        # Aplica mudanças se confirmado
        if success_count > 0 and not args.dry_run:
            if args.yes or Confirm.ask("\nDeseja aplicar as mudanças ao modelo?"):
                console.print("\n📥 Aplicando mudanças...")
                await agent.apply_refactored(results, dry_run=False)
                console.print("[green]✅ Mudanças aplicadas com sucesso![/green]")
            else:
                console.print("[yellow]Mudanças não aplicadas (dry-run).[/yellow]")
        
        return 0 if fail_count == 0 else 1
        
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        return 1
    finally:
        await agent.disconnect()


async def cmd_interactive(args):
    """Modo interativo para exploração e refatoração."""
    settings = get_settings()
    setup_logging(settings.log_level)
    
    console.print(Panel.fit("💬 [bold magenta]Modo Interativo[/bold magenta]"))
    console.print("Digite 'help' para ver comandos disponíveis, 'quit' para sair.\n")
    
    agent = RefactorAgent(mcp_path=args.mcp_path)
    
    try:
        await agent.connect()
        
        if args.model:
            await agent.discover_model(args.model)
            console.print(f"[green]✅ Modelo carregado: {args.model}[/green]\n")
        
        while True:
            try:
                cmd = Prompt.ask("[bold cyan]pbi-agent[/bold cyan]")
                cmd = cmd.strip().lower()
                
                if cmd in ("quit", "exit", "q"):
                    break
                
                elif cmd == "help":
                    console.print("""
[bold]Comandos disponíveis:[/bold]
  [cyan]load <path>[/cyan]       - Carrega um modelo semântico
  [cyan]tables[/cyan]            - Lista tabelas do modelo
  [cyan]measures[/cyan]          - Lista medidas do modelo
  [cyan]analyze <change>[/cyan]  - Analisa impacto de uma mudança
  [cyan]refactor <change>[/cyan] - Executa refatoração
  [cyan]validate <dax>[/cyan]    - Valida expressão DAX
  [cyan]quit[/cyan]              - Sai do modo interativo
                    """)
                
                elif cmd.startswith("load "):
                    path = cmd.replace("load ", "").strip()
                    await agent.discover_model(path)
                    console.print(f"[green]✅ Modelo carregado[/green]")
                
                elif cmd == "tables":
                    if agent.dependency_graph:
                        tables = list(agent.dependency_graph._tables.values())
                        for t in tables:
                            console.print(f"  • {t.name}")
                    else:
                        console.print("[yellow]Nenhum modelo carregado.[/yellow]")
                
                elif cmd == "measures":
                    if agent.dependency_graph:
                        measures = list(agent.dependency_graph._measures.values())
                        for m in measures:
                            console.print(f"  • {m.name}: {m.expression[:40]}...")
                    else:
                        console.print("[yellow]Nenhum modelo carregado.[/yellow]")
                
                elif cmd.startswith("analyze "):
                    change_desc = cmd.replace("analyze ", "").strip()
                    change = parse_change_description(change_desc)
                    if change:
                        impact = agent.analyze_impact(change)
                        console.print(f"[bold]Total impactado: {impact.total_impacted}[/bold]")
                    else:
                        console.print("[red]Formato de mudança inválido.[/red]")
                
                elif cmd.startswith("validate "):
                    from .validation import SyntaxValidator
                    dax = cmd.replace("validate ", "").strip()
                    validator = SyntaxValidator()
                    result = validator.validate(dax)
                    if result.is_valid:
                        console.print("[green]✅ Expressão válida[/green]")
                    else:
                        console.print(f"[red]❌ {result.error_message}[/red]")
                
                else:
                    console.print("[yellow]Comando não reconhecido. Digite 'help' para ajuda.[/yellow]")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Erro: {e}[/red]")
        
        console.print("\n[dim]Até logo![/dim]")
        return 0
        
    except Exception as e:
        console.print(f"[red]❌ Erro: {e}[/red]")
        return 1
    finally:
        await agent.disconnect()


def main():
    """Ponto de entrada principal da CLI."""
    parser = argparse.ArgumentParser(
        prog="pbi-refactor-agent",
        description="Agente para análise preditiva e refatoração de modelos Power BI"
    )
    parser.add_argument(
        "--mcp-path",
        default="pbi-mcp-server",
        help="Caminho para o executável do MCP Server"
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analisa impacto de uma mudança")
    analyze_parser.add_argument("--model", "-m", required=True, help="Caminho do modelo semântico")
    analyze_parser.add_argument("--change", "-c", required=True, help="Descrição da mudança")
    analyze_parser.add_argument("--output", "-o", help="Arquivo de saída para o relatório")
    analyze_parser.set_defaults(func=cmd_analyze)
    
    # Refactor command
    refactor_parser = subparsers.add_parser("refactor", help="Executa refatoração automática")
    refactor_parser.add_argument("--model", "-m", required=True, help="Caminho do modelo semântico")
    refactor_parser.add_argument("--change", "-c", required=True, help="Descrição da mudança")
    refactor_parser.add_argument("--output", "-o", help="Arquivo de saída para o relatório")
    refactor_parser.add_argument("--yes", "-y", action="store_true", help="Não pede confirmação")
    refactor_parser.add_argument("--dry-run", action="store_true", help="Simula sem aplicar")
    refactor_parser.set_defaults(func=cmd_refactor)
    
    # Interactive command
    interactive_parser = subparsers.add_parser("interactive", help="Modo interativo")
    interactive_parser.add_argument("--model", "-m", help="Caminho do modelo semântico (opcional)")
    interactive_parser.set_defaults(func=cmd_interactive)
    
    args = parser.parse_args()
    
    if hasattr(args, "func"):
        result = asyncio.run(args.func(args))
        sys.exit(result)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
