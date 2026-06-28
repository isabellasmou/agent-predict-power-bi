"""
Configurações do PBI Refactor Agent.

Utiliza Pydantic Settings para gerenciamento de configurações
via variáveis de ambiente e arquivo .env.
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Provedores de LLM suportados."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    GROQ = "groq"  # GRATUITO!
    GOOGLE = "google"  # Gemini 2.5 Flash - 20 req/dia gratuito


class LogLevel(str, Enum):
    """Níveis de log."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Configurações principais do agente."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # LLM API Keys
    openai_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Chave de API do OpenAI"
    )
    anthropic_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Chave de API do Anthropic"
    )
    
    # Azure OpenAI
    azure_openai_endpoint: Optional[str] = Field(
        default=None,
        description="Endpoint do Azure OpenAI"
    )
    azure_openai_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Chave de API do Azure OpenAI"
    )
    azure_openai_deployment: str = Field(
        default="gpt-4o",
        description="Nome do deployment Azure OpenAI"
    )
    
    # Groq (GRATUITO!)
    groq_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Chave de API do Groq (gratuito)"
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Modelo Groq a utilizar"
    )
    
    # Google AI Studio (Gemini)
    google_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Chave de API do Google AI Studio"
    )
    google_model: str = Field(
        default="gemini-2.5-flash",
        description="Modelo Google Gemini a utilizar"
    )
    
    # MCP Server
    mcp_server_path: Optional[Path] = Field(
        default=None,
        description="Caminho para o executável do MCP Server"
    )
    mcp_server_timeout: int = Field(
        default=30,
        description="Timeout em segundos para comunicação com MCP Server"
    )
    
    # LLM defaults
    default_llm_provider: LLMProvider = Field(
        default=LLMProvider.GROQ,
        description="Provedor de LLM padrão"
    )
    default_llm_model: str = Field(
        default="gpt-4o",
        description="Modelo de LLM padrão"
    )
    
    # Logging
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Nível de log"
    )
    log_format: str = Field(
        default="json",
        description="Formato de log (json ou text)"
    )
    
    # Validation
    validation_timeout: int = Field(
        default=60,
        description="Timeout em segundos para validação de expressões"
    )
    max_retries: int = Field(
        default=3,
        description="Número máximo de tentativas em caso de falha"
    )
    retry_delay: float = Field(
        default=1.0,
        description="Delay em segundos entre tentativas"
    )
    
    # Performance thresholds
    max_execution_time_ms: int = Field(
        default=5000,
        description="Tempo máximo de execução em milissegundos"
    )
    numeric_tolerance: float = Field(
        default=0.0001,
        description="Tolerância numérica para comparação de resultados"
    )
    
    def get_llm_api_key(self, provider: Optional[LLMProvider] = None) -> Optional[str]:
        """Retorna a chave de API para o provedor especificado."""
        provider = provider or self.default_llm_provider
        
        if provider == LLMProvider.OPENAI:
            return self.openai_api_key.get_secret_value() if self.openai_api_key else None
        elif provider == LLMProvider.ANTHROPIC:
            return self.anthropic_api_key.get_secret_value() if self.anthropic_api_key else None
        elif provider == LLMProvider.AZURE:
            return self.azure_openai_api_key.get_secret_value() if self.azure_openai_api_key else None
        elif provider == LLMProvider.GROQ:
            return self.groq_api_key.get_secret_value() if self.groq_api_key else None
        elif provider == LLMProvider.GOOGLE:
            return self.google_api_key.get_secret_value() if self.google_api_key else None
        
        return None
    
    def validate_llm_config(self, provider: Optional[LLMProvider] = None) -> bool:
        """Valida se a configuração do LLM está completa."""
        provider = provider or self.default_llm_provider
        
        if provider == LLMProvider.OPENAI:
            return self.openai_api_key is not None
        elif provider == LLMProvider.ANTHROPIC:
            return self.anthropic_api_key is not None
        elif provider == LLMProvider.AZURE:
            return (
                self.azure_openai_endpoint is not None
                and self.azure_openai_api_key is not None
            )
        elif provider == LLMProvider.GROQ:
            return self.groq_api_key is not None
        
        return False


@lru_cache
def get_settings() -> Settings:
    """Retorna as configurações do agente (singleton)."""
    return Settings()


# Modelos de LLM disponíveis por provedor
LLM_MODELS = {
    LLMProvider.OPENAI: [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
    ],
    LLMProvider.ANTHROPIC: [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    LLMProvider.AZURE: [
        "gpt-4o",
    ],
    LLMProvider.GROQ: [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
}
