"""
Configuração de Logging.

Configura logging estruturado com structlog para o agente.
"""

import logging
import sys
from typing import Optional

import structlog
from rich.console import Console
from rich.logging import RichHandler

from pbi_refactor_agent.config import LogLevel, get_settings


def setup_logging(
    level: Optional[LogLevel] = None,
    json_format: bool = False,
    log_file: Optional[str] = None
) -> None:
    """
    Configura o sistema de logging.
    
    Args:
        level: Nível de log (padrão: das configurações).
        json_format: Se True, usa formato JSON.
        log_file: Caminho para arquivo de log (opcional).
    """
    settings = get_settings()
    level = level or settings.log_level
    json_format = json_format or (settings.log_format == "json")
    
    # Configura nível de log
    log_level = getattr(logging, level.value, logging.INFO)
    
    # Handlers
    handlers = []
    
    if json_format:
        # Formato JSON para produção
        handlers.append(logging.StreamHandler(sys.stdout))
    else:
        # Formato rico para desenvolvimento
        console = Console(force_terminal=True)
        handlers.append(
            RichHandler(
                console=console,
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
                tracebacks_show_locals=True
            )
        )
    
    # Adiciona handler de arquivo se especificado
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
        handlers.append(file_handler)
    
    # Configura logging básico
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True
    )
    
    # Configura structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if json_format:
        # Processadores para JSON
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer()
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Processadores para console
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(
                    colors=True,
                    exception_formatter=structlog.dev.rich_traceback
                )
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Obtém um logger configurado.
    
    Args:
        name: Nome do logger (geralmente __name__).
        
    Returns:
        Logger configurado.
    """
    return structlog.get_logger(name)


class LogContext:
    """
    Context manager para adicionar contexto temporário ao logging.
    
    Uso:
        with LogContext(request_id="123", user="admin"):
            logger.info("Processando request")
    """
    
    def __init__(self, **kwargs):
        """
        Inicializa o contexto.
        
        Args:
            **kwargs: Pares chave-valor para adicionar ao contexto.
        """
        self._context = kwargs
    
    def __enter__(self):
        """Adiciona contexto."""
        structlog.contextvars.bind_contextvars(**self._context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Remove contexto."""
        for key in self._context:
            structlog.contextvars.unbind_contextvars(key)
