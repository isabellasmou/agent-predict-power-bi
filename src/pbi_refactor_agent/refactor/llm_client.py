"""
Cliente LLM para integração com múltiplos provedores.

Suporta OpenAI (GPT-4o), Anthropic (Claude 3.5 Sonnet), Azure OpenAI, Groq e Google Gemini.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
import re
import asyncio

import structlog
from openai import AsyncOpenAI, AsyncAzureOpenAI
from anthropic import AsyncAnthropic
from groq import AsyncGroq
from google import genai
from google.genai import types as genai_types

from pbi_refactor_agent.config import LLMProvider, Settings, get_settings

logger = structlog.get_logger(__name__)


class BaseLLMClient(ABC):
    """Cliente LLM base abstrato."""
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """
        Gera uma completação de texto.
        
        Args:
            prompt: Prompt do usuário.
            system_prompt: Prompt de sistema (opcional).
            temperature: Temperatura para geração (0.0 = determinístico).
            max_tokens: Número máximo de tokens na resposta.
            **kwargs: Argumentos adicionais específicos do provedor.
            
        Returns:
            Texto gerado pelo modelo.
        """
        pass
    
    @property
    @abstractmethod
    def provider(self) -> str:
        """Retorna o nome do provedor."""
        pass
    
    @property
    @abstractmethod
    def model(self) -> str:
        """Retorna o nome do modelo."""
        pass


class OpenAIClient(BaseLLMClient):
    """Cliente para OpenAI (GPT-4o)."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        **kwargs
    ):
        """
        Inicializa o cliente OpenAI.
        
        Args:
            api_key: Chave de API do OpenAI.
            model: Nome do modelo a utilizar.
            **kwargs: Argumentos adicionais para o cliente.
        """
        self._client = AsyncOpenAI(api_key=api_key, **kwargs)
        self._model = model
        
        logger.info("Cliente OpenAI inicializado", model=model)
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Gera completação usando OpenAI."""
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        logger.debug(
            "Enviando requisição para OpenAI",
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        result = response.choices[0].message.content
        
        logger.debug(
            "Resposta recebida do OpenAI",
            tokens_used=response.usage.total_tokens if response.usage else None
        )
        
        return result
    
    @property
    def provider(self) -> str:
        return "openai"
    
    @property
    def model(self) -> str:
        return self._model


class AnthropicClient(BaseLLMClient):
    """Cliente para Anthropic (Claude 3.5 Sonnet)."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        **kwargs
    ):
        """
        Inicializa o cliente Anthropic.
        
        Args:
            api_key: Chave de API do Anthropic.
            model: Nome do modelo a utilizar.
            **kwargs: Argumentos adicionais para o cliente.
        """
        self._client = AsyncAnthropic(api_key=api_key, **kwargs)
        self._model = model
        
        logger.info("Cliente Anthropic inicializado", model=model)
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Gera completação usando Anthropic."""
        logger.debug(
            "Enviando requisição para Anthropic",
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt or "",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            **kwargs
        )
        
        result = response.content[0].text
        
        logger.debug(
            "Resposta recebida do Anthropic",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens
        )
        
        return result
    
    @property
    def provider(self) -> str:
        return "anthropic"
    
    @property
    def model(self) -> str:
        return self._model


class AzureOpenAIClient(BaseLLMClient):
    """Cliente para Azure OpenAI."""
    
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = "2024-02-15-preview",
        **kwargs
    ):
        """
        Inicializa o cliente Azure OpenAI.
        
        Args:
            endpoint: Endpoint do Azure OpenAI.
            api_key: Chave de API.
            deployment: Nome do deployment.
            api_version: Versão da API.
            **kwargs: Argumentos adicionais.
        """
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            **kwargs
        )
        self._deployment = deployment
        
        logger.info("Cliente Azure OpenAI inicializado", deployment=deployment)
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Gera completação usando Azure OpenAI."""
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        logger.debug(
            "Enviando requisição para Azure OpenAI",
            deployment=self._deployment,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        result = response.choices[0].message.content
        
        logger.debug(
            "Resposta recebida do Azure OpenAI",
            tokens_used=response.usage.total_tokens if response.usage else None
        )
        
        return result
    
    @property
    def provider(self) -> str:
        return "azure"
    
    @property
    def model(self) -> str:
        return self._deployment


class GroqClient(BaseLLMClient):
    """Cliente para Groq (GRATUITO E RÁPIDO!)."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        **kwargs
    ):
        """
        Inicializa o cliente Groq.
        
        Args:
            api_key: Chave de API do Groq.
            model: Nome do modelo a utilizar.
            **kwargs: Argumentos adicionais.
        """
        self._client = AsyncGroq(api_key=api_key, **kwargs)
        self._model = model
        
        logger.info("Cliente Groq inicializado", model=model)
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Gera completação usando Groq."""
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        logger.debug(
            "Enviando requisição para Groq",
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        result = response.choices[0].message.content
        
        logger.debug(
            "Resposta recebida do Groq",
            tokens_used=response.usage.total_tokens if response.usage else None
        )
        
        return result
    
    @property
    def provider(self) -> str:
        return "groq"
    
    @property
    def model(self) -> str:
        return self._model


class GoogleClient(BaseLLMClient):
    """Cliente para Google Gemini (gratuito com limites)."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        **kwargs
    ):
        """
        Inicializa o cliente Google Gemini.
        
        Args:
            api_key: Chave de API do Google AI Studio.
            model: Nome do modelo a utilizar.
            **kwargs: Argumentos adicionais.
        """
        self._client = genai.Client(api_key=api_key)
        self._model_name = model
        self._fallback_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash"]
        
        logger.info("Cliente Google Gemini inicializado", model=model)
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Gera completação usando Google Gemini com retry automático."""
        # Gemini usa system_instruction no modelo, mas podemos concatenar ao prompt
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        logger.debug(
            "Enviando requisição para Google Gemini",
            model=self._model_name,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        generation_config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        # Retry com exponential backoff para rate limits e sobrecarga
        # Limites otimizados para TCC: 2 tentativas, max 10s de espera
        max_retries = 2
        base_delay = 2.0
        max_delay = 10.0  # Não esperar mais que 10s
        
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model_name,
                    contents=full_prompt,
                    config=generation_config,
                    **kwargs
                )
                
                result = response.text or ""
                
                # Se resposta vazia e não é última tentativa, retry
                if not result and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Resposta vazia recebida, aguardando retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay_seconds=delay
                    )
                    await asyncio.sleep(delay)
                    continue
                
                if not result:
                    raise ValueError("Google Gemini retornou resposta vazia após todas as tentativas")
                
                logger.debug(
                    "Resposta recebida do Google Gemini",
                    model=self._model_name,
                    attempt=attempt + 1
                )
                
                return result
                
            except Exception as exc:
                message = str(exc)
                
                # Detectar erros que justificam retry
                is_rate_limit = "429" in message or "RESOURCE_EXHAUSTED" in message
                is_unavailable = "503" in message or "UNAVAILABLE" in message
                is_model_not_found = "is not found" in message or "not supported for generateContent" in message
                
                # Fallback de modelo (só na primeira tentativa)
                if is_model_not_found and attempt == 0:
                    for fallback in self._fallback_models:
                        if fallback == self._model_name:
                            continue
                        logger.warning(
                            "Modelo Gemini indisponivel, tentando fallback",
                            configured_model=self._model_name,
                            fallback_model=fallback
                        )
                        self._model_name = fallback
                        # Tentar novamente com o modelo de fallback
                        try:
                            response = await asyncio.to_thread(
                                self._client.models.generate_content,
                                model=self._model_name,
                                contents=full_prompt,
                                config=generation_config,
                                **kwargs
                            )
                            result = response.text or ""
                            if not result:
                                raise ValueError("Google Gemini retornou resposta vazia")
                            
                            logger.debug(
                                "Resposta recebida do Google Gemini (fallback)",
                                model=self._model_name
                            )
                            return result
                        except Exception:
                            # Se fallback também falhar, continuar com retry normal
                            break
                
                # Retry para rate limit ou sobrecarga
                if (is_rate_limit or is_unavailable) and attempt < max_retries - 1:
                    # Verificar se é limite diário (não adianta retry)
                    is_daily_quota = "Per Day" in message or "PerDay" in message
                    if is_daily_quota:
                        logger.error(
                            "Quota diária do Google Gemini esgotada",
                            model=self._model_name,
                            message="Limite diário de requisições atingido. Aguarde até amanhã ou use outro provedor."
                        )
                        raise  # Não faz retry para quota diária
                    
                    # Tentar extrair delay da mensagem de erro
                    retry_match = re.search(r"retry in ([\d.]+)s", message, re.IGNORECASE)
                    if retry_match:
                        delay = min(float(retry_match.group(1)), max_delay)
                    else:
                        # Exponential backoff
                        delay = min(base_delay * (2 ** attempt), max_delay)
                    
                    logger.warning(
                        "Rate limit ou sobrecarga detectado, aguardando retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay_seconds=delay,
                        delay_original=float(retry_match.group(1)) if retry_match else None,
                        error_type="rate_limit" if is_rate_limit else "unavailable"
                    )
                    
                    await asyncio.sleep(delay)
                    continue
                
                # Se não é erro de retry ou última tentativa, propagar erro
                raise
    
    @property
    def provider(self) -> str:
        return "google"
    
    @property
    def model(self) -> str:
        return self._model_name


class LLMClient:
    """
    Cliente LLM unificado com suporte a múltiplos provedores.
    
    Factory que cria e gerencia clientes para diferentes provedores de LLM.
    """
    
    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        settings: Optional[Settings] = None
    ):
        """
        Inicializa o cliente LLM.
        
        Args:
            provider: Provedor de LLM (padrão: das configurações).
            model: Modelo específico (padrão: das configurações).
            settings: Configurações (padrão: singleton).
        """
        self._settings = settings or get_settings()
        self._provider = provider or self._settings.default_llm_provider
        
        # Use modelo específico do provedor se não fornecido
        if model is None:
            if self._provider == LLMProvider.GROQ:
                self._model = self._settings.groq_model
            elif self._provider == LLMProvider.GOOGLE:
                self._model = self._settings.google_model
            else:
                self._model = self._settings.default_llm_model
        else:
            self._model = model
        
        self._client = self._create_client()
    
    def _create_client(self) -> BaseLLMClient:
        """Cria o cliente específico do provedor."""
        if self._provider == LLMProvider.OPENAI:
            api_key = self._settings.get_llm_api_key(LLMProvider.OPENAI)
            if not api_key:
                raise ValueError("OpenAI API key não configurada")
            model = self._model or self._settings.default_llm_model
            return OpenAIClient(api_key=api_key, model=model)
        
        elif self._provider == LLMProvider.ANTHROPIC:
            api_key = self._settings.get_llm_api_key(LLMProvider.ANTHROPIC)
            if not api_key:
                raise ValueError("Anthropic API key não configurada")
            model = self._model or "claude-3-5-sonnet-20241022"
            return AnthropicClient(api_key=api_key, model=model)
        
        elif self._provider == LLMProvider.AZURE:
            api_key = self._settings.get_llm_api_key(LLMProvider.AZURE)
            endpoint = self._settings.azure_openai_endpoint
            deployment = self._settings.azure_openai_deployment
            
            if not api_key or not endpoint:
                raise ValueError("Azure OpenAI não configurado corretamente")
            
            return AzureOpenAIClient(
                endpoint=endpoint,
                api_key=api_key,
                deployment=deployment
            )
        
        elif self._provider == LLMProvider.GROQ:
            api_key = self._settings.get_llm_api_key(LLMProvider.GROQ)
            if not api_key:
                raise ValueError("Groq API key não configurada. Obtenha em https://console.groq.com/")
            model = self._model or self._settings.groq_model
            return GroqClient(api_key=api_key, model=model)
        
        elif self._provider == LLMProvider.GOOGLE:
            api_key = self._settings.get_llm_api_key(LLMProvider.GOOGLE)
            if not api_key:
                raise ValueError("Google API key não configurada. Obtenha em https://aistudio.google.com/")
            model = self._model or self._settings.google_model
            return GoogleClient(api_key=api_key, model=model)
        
        else:
            raise ValueError(f"Provedor não suportado: {self._provider}")
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """
        Gera uma completação de texto.
        
        Args:
            prompt: Prompt do usuário.
            system_prompt: Prompt de sistema (opcional).
            temperature: Temperatura para geração.
            max_tokens: Número máximo de tokens.
            **kwargs: Argumentos adicionais.
            
        Returns:
            Texto gerado.
        """
        return await self._client.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    
    @property
    def provider(self) -> str:
        """Retorna o nome do provedor."""
        return self._client.provider
    
    @property
    def model(self) -> str:
        """Retorna o nome do modelo."""
        return self._client.model


def create_llm_client(
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None
) -> LLMClient:
    """
    Factory function para criar cliente LLM.
    
    Args:
        provider: Provedor de LLM.
        model: Modelo específico.
        
    Returns:
        Cliente LLM configurado.
    """
    return LLMClient(provider=provider, model=model)
