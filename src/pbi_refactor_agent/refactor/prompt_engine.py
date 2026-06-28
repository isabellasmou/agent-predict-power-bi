"""
Motor de Engenharia de Prompts para Refatoração de DAX.

Define templates e estratégias de prompts especializados
para refatoração de expressões DAX com LLMs.
"""

from enum import Enum
from typing import Any, Optional

import structlog

from pbi_refactor_agent.models import ChangeType, ImpactedObject, SemanticObject

logger = structlog.get_logger(__name__)


class DAXPromptTemplate(str, Enum):
    """Templates de prompt pré-definidos."""
    
    RENAME_COLUMN = "rename_column"
    RENAME_TABLE = "rename_table"
    RENAME_MEASURE = "rename_measure"
    GENERAL_REFACTOR = "general_refactor"
    EXPLAIN_EXPRESSION = "explain_expression"
    OPTIMIZE_EXPRESSION = "optimize_expression"


class PromptEngine:
    """
    Motor de engenharia de prompts para DAX.
    
    Gera prompts otimizados para diferentes cenários de refatoração,
    incluindo contexto do modelo e instruções específicas.
    """
    
    # System prompt base para refatoração de DAX
    SYSTEM_PROMPT = """Você é um especialista em Power BI e DAX (Data Analysis Expressions).
Sua tarefa é refatorar expressões DAX preservando exatamente a mesma lógica de negócio.

REGRAS IMPORTANTES:
1. NUNCA altere a lógica de negócio - apenas aplique as mudanças estruturais solicitadas
2. Mantenha EXATAMENTE a formatação, indentação e estilo do original
3. Preserve todos os comentários existentes (linhas com //)
4. Se houver ambiguidade, escolha a interpretação mais segura
5. Retorne APENAS o código DAX refatorado, sem explicações adicionais
6. Se não for possível refatorar com segurança, retorne "ERRO: <motivo>"

REGRAS DE ESTILO OBRIGATÓRIAS:
- Use SEMPRE o mesmo formato de referência que está no código original
- Se o original usa  dGeral[Coluna]  → mantenha  dGeral[Coluna]  (SEM aspas simples)
- Se o original usa  'dGeral'[Coluna] → mantenha  'dGeral'[Coluna]  (COM aspas simples)
- NUNCA adicione aspas simples ao redor de nomes de tabela que não tinham aspas no original
- NUNCA remova aspas simples de nomes de tabela que tinham aspas no original

FORMATO DE RESPOSTA:
Retorne apenas o código DAX entre tags <dax></dax>:
<dax>
-- código DAX aqui
</dax>"""

    # Templates específicos por tipo de mudança
    TEMPLATES = {
        DAXPromptTemplate.RENAME_COLUMN: """
TAREFA: Refatorar a expressão DAX abaixo para refletir o renomeio de uma coluna.

MUDANÇA:
- Tabela: {table_name}
- Coluna antiga: [{old_name}]
- Coluna nova: [{new_name}]

INSTRUÇÃO CRÍTICA DE ESTILO:
Substitua APENAS as referências à coluna renomeada.
Mantenha EXATAMENTE o mesmo formato de referência de tabela que está no código original.
Se o original usa  {table_name}[{old_name}]  (sem aspas), use  {table_name}[{new_name}]  (sem aspas).
NÃO adicione aspas simples ao redor do nome da tabela se elas não estavam no original.

EXEMPLO CORRETO:
  Original:  {table_name}[{old_name}]
  Resultado: {table_name}[{new_name}]

EXEMPLO ERRADO (não faça isso):
  Original:  {table_name}[{old_name}]
  Resultado: '{table_name}'[{new_name}]  ← ERRADO, adicionou aspas desnecessárias

EXPRESSÃO ORIGINAL:
```dax
{expression}
```

CONTEXTO ADICIONAL:
- Objeto: {object_name} ({object_type})
- Descrição: {description}

Retorne a expressão refatorada preservando o estilo original.""",

        DAXPromptTemplate.RENAME_TABLE: """
TAREFA: Refatorar a expressão DAX abaixo para refletir o renomeio de uma tabela.

MUDANÇA:
- Tabela antiga: '{old_table_name}'
- Tabela nova: '{new_table_name}'

SUBSTITUIÇÕES NECESSÁRIAS:
- Todas as referências a '{old_table_name}' devem ser substituídas por '{new_table_name}'
- Manter a mesma estrutura de aspas (se usava aspas simples, manter)

EXPRESSÃO ORIGINAL:
```dax
{expression}
```

CONTEXTO:
- Objeto: {object_name} ({object_type})

Retorne a expressão refatorada.""",

        DAXPromptTemplate.RENAME_MEASURE: """
TAREFA: Refatorar a expressão DAX abaixo para refletir o renomeio de uma medida.

MUDANÇA:
- Medida antiga: [{old_measure_name}]
- Medida nova: [{new_measure_name}]

EXPRESSÃO ORIGINAL:
```dax
{expression}
```

CONTEXTO:
- Objeto: {object_name} ({object_type})

Retorne a expressão refatorada.""",

        DAXPromptTemplate.GENERAL_REFACTOR: """
TAREFA: Refatorar a expressão DAX abaixo aplicando as seguintes mudanças.

MUDANÇAS SOLICITADAS:
{changes_description}

EXPRESSÃO ORIGINAL:
```dax
{expression}
```

CONTEXTO:
- Objeto: {object_name} ({object_type})
- Descrição: {description}

Retorne a expressão refatorada preservando a lógica de negócio.""",

        DAXPromptTemplate.EXPLAIN_EXPRESSION: """
TAREFA: Explique a seguinte expressão DAX.

EXPRESSÃO:
```dax
{expression}
```

CONTEXTO:
- Objeto: {object_name} ({object_type})
- Tabela: {table_name}

Forneça:
1. Resumo do que a expressão faz
2. Lista de dependências (tabelas/colunas/medidas referenciadas)
3. Identificação de possíveis problemas ou melhorias""",

        DAXPromptTemplate.OPTIMIZE_EXPRESSION: """
TAREFA: Otimize a seguinte expressão DAX para melhor performance.

EXPRESSÃO ORIGINAL:
```dax
{expression}
```

CONTEXTO:
- Objeto: {object_name} ({object_type})
- Descrição: {description}

REGRAS:
1. Preserve a lógica de negócio exatamente
2. Aplique best practices de DAX (evitar iteradores desnecessários, usar CALCULATE corretamente, etc.)
3. Documente cada otimização aplicada

Retorne a expressão otimizada."""
    }

    def __init__(self):
        """Inicializa o motor de prompts."""
        self._custom_templates: dict[str, str] = {}
    
    def get_system_prompt(self) -> str:
        """Retorna o system prompt padrão."""
        return self.SYSTEM_PROMPT
    
    def build_prompt(
        self,
        template: DAXPromptTemplate,
        **kwargs
    ) -> str:
        """
        Constrói um prompt a partir de um template.
        
        Args:
            template: Template de prompt a usar.
            **kwargs: Variáveis para preencher o template.
            
        Returns:
            Prompt construído.
        """
        template_str = self.TEMPLATES.get(template)
        
        if not template_str:
            raise ValueError(f"Template não encontrado: {template}")
        
        try:
            prompt = template_str.format(**kwargs)
            logger.debug("Prompt construído", template=template.value)
            return prompt
        except KeyError as e:
            logger.error(
                "Variável faltando no template",
                template=template.value,
                missing_key=str(e)
            )
            raise ValueError(f"Variável faltando no template: {e}")
    
    def build_rename_column_prompt(
        self,
        impacted_object: ImpactedObject,
        table_name: str,
        old_name: str,
        new_name: str
    ) -> str:
        """
        Constrói prompt para renomeio de coluna.
        
        Args:
            impacted_object: Objeto impactado.
            table_name: Nome da tabela.
            old_name: Nome antigo da coluna.
            new_name: Novo nome da coluna.
            
        Returns:
            Prompt construído.
        """
        obj = impacted_object.object
        
        return self.build_prompt(
            template=DAXPromptTemplate.RENAME_COLUMN,
            table_name=table_name,
            old_name=old_name,
            new_name=new_name,
            expression=obj.expression or "",
            object_name=obj.name,
            object_type=obj.object_type,
            description=obj.description or "N/A"
        )
    
    def build_rename_table_prompt(
        self,
        impacted_object: ImpactedObject,
        old_table_name: str,
        new_table_name: str
    ) -> str:
        """
        Constrói prompt para renomeio de tabela.
        
        Args:
            impacted_object: Objeto impactado.
            old_table_name: Nome antigo da tabela.
            new_table_name: Novo nome da tabela.
            
        Returns:
            Prompt construído.
        """
        obj = impacted_object.object
        
        return self.build_prompt(
            template=DAXPromptTemplate.RENAME_TABLE,
            old_table_name=old_table_name,
            new_table_name=new_table_name,
            expression=obj.expression or "",
            object_name=obj.name,
            object_type=obj.object_type
        )
    
    def build_rename_measure_prompt(
        self,
        impacted_object: ImpactedObject,
        old_measure_name: str,
        new_measure_name: str
    ) -> str:
        """
        Constrói prompt para renomeio de medida.
        
        Args:
            impacted_object: Objeto impactado.
            old_measure_name: Nome antigo da medida.
            new_measure_name: Novo nome da medida.
            
        Returns:
            Prompt construído.
        """
        obj = impacted_object.object
        
        return self.build_prompt(
            template=DAXPromptTemplate.RENAME_MEASURE,
            old_measure_name=old_measure_name,
            new_measure_name=new_measure_name,
            expression=obj.expression or "",
            object_name=obj.name,
            object_type=obj.object_type
        )
    
    def build_general_refactor_prompt(
        self,
        impacted_object: ImpactedObject,
        changes_description: str
    ) -> str:
        """
        Constrói prompt para refatoração genérica.
        
        Args:
            impacted_object: Objeto impactado.
            changes_description: Descrição das mudanças a aplicar.
            
        Returns:
            Prompt construído.
        """
        obj = impacted_object.object
        
        return self.build_prompt(
            template=DAXPromptTemplate.GENERAL_REFACTOR,
            changes_description=changes_description,
            expression=obj.expression or "",
            object_name=obj.name,
            object_type=obj.object_type,
            description=obj.description or "N/A"
        )
    
    def add_custom_template(self, name: str, template: str) -> None:
        """
        Adiciona um template customizado.
        
        Args:
            name: Nome do template.
            template: String do template.
        """
        self._custom_templates[name] = template
        logger.info("Template customizado adicionado", name=name)
    
    def build_custom_prompt(self, template_name: str, **kwargs) -> str:
        """
        Constrói prompt a partir de template customizado.
        
        Args:
            template_name: Nome do template customizado.
            **kwargs: Variáveis para o template.
            
        Returns:
            Prompt construído.
        """
        if template_name not in self._custom_templates:
            raise ValueError(f"Template customizado não encontrado: {template_name}")
        
        return self._custom_templates[template_name].format(**kwargs)
    
    def extract_dax_from_response(self, response: str) -> Optional[str]:
        """
        Extrai código DAX de uma resposta do LLM.
        
        Args:
            response: Resposta completa do LLM.
            
        Returns:
            Código DAX extraído ou None se não encontrado.
        """
        import re
        
        # Tenta extrair de tags <dax></dax>
        dax_match = re.search(r"<dax>(.*?)</dax>", response, re.DOTALL)
        if dax_match:
            return dax_match.group(1).strip()
        
        # Tenta extrair de blocos de código markdown
        code_match = re.search(r"```(?:dax)?\n?(.*?)```", response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        
        # Se não encontrar tags, assume que toda a resposta é código DAX
        # (remove linhas que parecem ser explicações)
        lines = response.strip().split("\n")
        dax_lines = []
        
        for line in lines:
            # Ignora linhas que parecem ser explicações
            if line.strip().startswith(("Explicação:", "Nota:", "Note:", "ERRO:")):
                continue
            dax_lines.append(line)
        
        result = "\n".join(dax_lines).strip()
        
        if result:
            return result
        
        return None
    
    def validate_response(self, response: str) -> tuple[bool, Optional[str]]:
        """
        Valida se a resposta do LLM contém código DAX válido.
        
        Args:
            response: Resposta do LLM.
            
        Returns:
            Tupla (é_válido, mensagem_erro).
        """
        if not response:
            return False, "Resposta vazia"
        
        if response.strip().startswith("ERRO:"):
            error_msg = response.strip()[5:].strip()
            return False, f"LLM reportou erro: {error_msg}"
        
        dax_code = self.extract_dax_from_response(response)
        
        if not dax_code:
            return False, "Não foi possível extrair código DAX da resposta"
        
        # Validação básica - pelo menos alguma estrutura DAX
        dax_upper = dax_code.upper()
        has_dax_structure = any([
            "[" in dax_code and "]" in dax_code,  # Referência a coluna/medida
            "CALCULATE" in dax_upper,
            "SUM" in dax_upper,
            "FILTER" in dax_upper,
            "VAR" in dax_upper,
            "RETURN" in dax_upper,
        ])
        
        if not has_dax_structure:
            return False, "Resposta não parece conter código DAX válido"
        
        return True, None
