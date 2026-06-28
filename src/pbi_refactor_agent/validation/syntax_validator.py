"""
Validador de Sintaxe DAX.

Responsável por validar se expressões DAX estão sintaticamente corretas.
"""

import re
from typing import Optional

import structlog

from pbi_refactor_agent.models import SyntaxValidation

logger = structlog.get_logger(__name__)


class SyntaxValidator:
    """
    Validador de sintaxe de expressões DAX.
    
    Realiza validação local (heurística) e pode integrar
    com o MCP Server para validação completa.
    """
    
    # Funções DAX comuns (lista parcial para validação)
    DAX_FUNCTIONS = {
        # Agregação
        "SUM", "SUMX", "AVERAGE", "AVERAGEX", "COUNT", "COUNTX",
        "COUNTA", "COUNTBLANK", "COUNTROWS", "MAX", "MAXX", "MIN", "MINX",
        "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK",
        
        # Filtro
        "FILTER", "ALL", "ALLEXCEPT", "ALLSELECTED", "VALUES", "DISTINCT",
        "SELECTEDVALUE", "HASONEVALUE", "HASONEFILTER", "ISFILTERED",
        "ISCROSSFILTERED", "KEEPFILTERS", "REMOVEFILTERS",
        
        # Cálculo
        "CALCULATE", "CALCULATETABLE", "EARLIER", "EARLIEST",
        
        # Relacionamento
        "RELATED", "RELATEDTABLE", "USERELATIONSHIP", "CROSSFILTER",
        
        # Tabela
        "ADDCOLUMNS", "SELECTCOLUMNS", "SUMMARIZE", "SUMMARIZECOLUMNS",
        "GROUPBY", "TOPN", "GENERATE", "GENERATEALL", "CROSSJOIN",
        "UNION", "INTERSECT", "EXCEPT", "NATURALINNERJOIN", "NATURALLEFTOUTERJOIN",
        "ROW", "DATATABLE", "TREATAS",
        
        # Texto
        "CONCATENATE", "CONCATENATEX", "FORMAT", "LEFT", "RIGHT", "MID",
        "LEN", "UPPER", "LOWER", "TRIM", "SUBSTITUTE", "REPLACE", "SEARCH",
        "FIND", "EXACT", "FIXED", "REPT", "UNICHAR", "UNICODE", "VALUE",
        
        # Lógica
        "IF", "SWITCH", "AND", "OR", "NOT", "TRUE", "FALSE", "IFERROR",
        "ISBLANK", "ISERROR", "ISLOGICAL", "ISNONTEXT", "ISNUMBER", "ISTEXT",
        "COALESCE", "BLANK",
        
        # Data/Hora
        "DATE", "DATEVALUE", "DAY", "MONTH", "YEAR", "HOUR", "MINUTE", "SECOND",
        "NOW", "TODAY", "WEEKDAY", "WEEKNUM", "EOMONTH", "EDATE",
        "DATEDIFF", "DATEADD", "CALENDAR", "CALENDARAUTO",
        
        # Time Intelligence
        "DATESINPERIOD", "DATESBETWEEN", "DATESYTD", "DATESQTD", "DATESMTD",
        "TOTALYTD", "TOTALQTD", "TOTALMTD", "SAMEPERIODLASTYEAR",
        "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH", "PREVIOUSDAY",
        "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
        "PARALLELPERIOD", "STARTOFYEAR", "STARTOFQUARTER", "STARTOFMONTH",
        "ENDOFYEAR", "ENDOFQUARTER", "ENDOFMONTH",
        "OPENINGBALANCEYEAR", "OPENINGBALANCEQUARTER", "OPENINGBALANCEMONTH",
        "CLOSINGBALANCEYEAR", "CLOSINGBALANCEQUARTER", "CLOSINGBALANCEMONTH",
        "FIRSTDATE", "LASTDATE", "FIRSTNONBLANK", "LASTNONBLANK",
        
        # Matemática
        "ABS", "CEILING", "FLOOR", "ROUND", "ROUNDUP", "ROUNDDOWN",
        "TRUNC", "INT", "MOD", "POWER", "SQRT", "EXP", "LN", "LOG", "LOG10",
        "SIGN", "RAND", "RANDBETWEEN", "PI", "EVEN", "ODD", "FACT",
        "GCD", "LCM", "QUOTIENT", "DIVIDE",
        
        # Estatística
        "MEDIAN", "MEDIANX", "PERCENTILE.INC", "PERCENTILE.EXC",
        "PERCENTILEX.INC", "PERCENTILEX.EXC", "STDEV.S", "STDEV.P",
        "STDEVX.S", "STDEVX.P", "VAR.S", "VAR.P", "VARX.S", "VARX.P",
        "RANK.EQ", "RANKX",
        
        # Informação
        "ISEMPTY", "USERCULTURE", "USERNAME", "USERPRINCIPALNAME",
        "CUSTOMDATA", "PATH", "PATHCONTAINS", "PATHITEM", "PATHITEMREVERSE",
        "PATHLENGTH",
        
        # Variáveis
        "VAR", "RETURN",
    }
    
    # Padrões de sintaxe
    COLUMN_REFERENCE_PATTERN = re.compile(
        r"'?[^'\[\]]+?'?\[[^\]]+\]"
    )
    
    FUNCTION_CALL_PATTERN = re.compile(
        r"([A-Z_][A-Z0-9_\.]*)\s*\(",
        re.IGNORECASE
    )
    
    STRING_LITERAL_PATTERN = re.compile(
        r'"[^"]*"'
    )
    
    def __init__(self, mcp_client=None):
        """
        Inicializa o validador.
        
        Args:
            mcp_client: Cliente MCP para validação via servidor (opcional).
        """
        self._mcp_client = mcp_client
    
    def validate(self, expression: str) -> SyntaxValidation:
        """
        Valida a sintaxe de uma expressão DAX.
        
        Args:
            expression: Expressão DAX a validar.
            
        Returns:
            Resultado da validação.
        """
        if not expression or not expression.strip():
            return SyntaxValidation(
                is_valid=False,
                error_message="Expressão vazia"
            )
        
        logger.debug("Validando sintaxe DAX", expression_length=len(expression))
        
        # Executa validações locais
        validation_checks = [
            self._check_brackets_balance,
            self._check_parentheses_balance,
            self._check_quotes_balance,
            self._check_function_names,
            self._check_column_references,
            self._check_common_errors,
        ]
        
        for check in validation_checks:
            result = check(expression)
            if not result.is_valid:
                logger.warning(
                    "Erro de sintaxe detectado",
                    error=result.error_message
                )
                return result
        
        logger.debug("Sintaxe validada com sucesso")
        
        return SyntaxValidation(is_valid=True)
    
    async def validate_with_server(self, expression: str) -> SyntaxValidation:
        """
        Valida a sintaxe usando o MCP Server para validação completa.
        
        Args:
            expression: Expressão DAX a validar.
            
        Returns:
            Resultado da validação.
        """
        # Primeiro faz validação local
        local_result = self.validate(expression)
        if not local_result.is_valid:
            return local_result
        
        # Se tiver cliente MCP, usa validação do servidor
        if self._mcp_client:
            try:
                # Tenta compilar a expressão via MCP
                result = await self._mcp_client.validate_expression(expression)
                
                if result.get("is_valid"):
                    return SyntaxValidation(is_valid=True)
                else:
                    return SyntaxValidation(
                        is_valid=False,
                        error_message=result.get("error_message"),
                        error_line=result.get("error_line"),
                        error_column=result.get("error_column")
                    )
            except Exception as e:
                logger.error("Erro ao validar via MCP", error=str(e))
                # Retorna resultado da validação local em caso de falha
                return local_result
        
        return local_result
    
    def _check_brackets_balance(self, expression: str) -> SyntaxValidation:
        """Verifica se colchetes estão balanceados."""
        # Remove strings para não contar colchetes dentro delas
        expr_no_strings = self.STRING_LITERAL_PATTERN.sub("", expression)
        
        open_count = expr_no_strings.count("[")
        close_count = expr_no_strings.count("]")
        
        if open_count != close_count:
            return SyntaxValidation(
                is_valid=False,
                error_message=f"Colchetes desbalanceados: {open_count} '[' e {close_count} ']'"
            )
        
        return SyntaxValidation(is_valid=True)
    
    def _check_parentheses_balance(self, expression: str) -> SyntaxValidation:
        """Verifica se parênteses estão balanceados."""
        expr_no_strings = self.STRING_LITERAL_PATTERN.sub("", expression)
        
        count = 0
        line = 1
        col = 1
        
        for char in expr_no_strings:
            if char == "(":
                count += 1
            elif char == ")":
                count -= 1
                if count < 0:
                    return SyntaxValidation(
                        is_valid=False,
                        error_message="Parêntese de fechamento sem correspondente",
                        error_line=line,
                        error_column=col
                    )
            elif char == "\n":
                line += 1
                col = 0
            col += 1
        
        if count != 0:
            return SyntaxValidation(
                is_valid=False,
                error_message=f"Parênteses desbalanceados: {count} parêntese(s) não fechado(s)"
            )
        
        return SyntaxValidation(is_valid=True)
    
    def _check_quotes_balance(self, expression: str) -> SyntaxValidation:
        """Verifica se aspas estão balanceadas."""
        # Conta aspas duplas (ignorando escaped)
        in_string = False
        quote_count = 0
        
        i = 0
        while i < len(expression):
            char = expression[i]
            
            if char == '"':
                # Verifica se é aspas escapada (dupla dentro de string)
                if in_string and i + 1 < len(expression) and expression[i + 1] == '"':
                    i += 2
                    continue
                
                in_string = not in_string
                quote_count += 1
            
            i += 1
        
        if in_string:
            return SyntaxValidation(
                is_valid=False,
                error_message="String não fechada (aspas desbalanceadas)"
            )
        
        return SyntaxValidation(is_valid=True)
    
    def _check_function_names(self, expression: str) -> SyntaxValidation:
        """Verifica se nomes de funções são válidos."""
        expr_no_strings = self.STRING_LITERAL_PATTERN.sub("", expression)
        
        matches = self.FUNCTION_CALL_PATTERN.findall(expr_no_strings)
        
        unknown_functions = []
        for func_name in matches:
            # Normaliza o nome da função
            func_upper = func_name.upper().replace(".", ".")
            
            # Ignora se parece ser uma medida/coluna entre colchetes antes
            if func_name not in self.DAX_FUNCTIONS:
                # Verifica se não é uma função conhecida
                if not any(
                    func_upper.startswith(known)
                    for known in self.DAX_FUNCTIONS
                ):
                    unknown_functions.append(func_name)
        
        # Por enquanto, apenas loga funções desconhecidas
        # Não retorna erro pois podem ser funções novas ou customizadas
        if unknown_functions:
            logger.debug(
                "Funções possivelmente desconhecidas",
                functions=unknown_functions[:5]
            )
        
        return SyntaxValidation(is_valid=True)
    
    def _check_column_references(self, expression: str) -> SyntaxValidation:
        """Verifica formato de referências a colunas."""
        expr_no_strings = self.STRING_LITERAL_PATTERN.sub("", expression)
        
        # Verifica referências malformadas
        # Exemplo: ['Tabela' sem fechar
        if "[''" in expr_no_strings or "'']" in expr_no_strings:
            return SyntaxValidation(
                is_valid=False,
                error_message="Referência a coluna malformada"
            )
        
        return SyntaxValidation(is_valid=True)
    
    def _check_common_errors(self, expression: str) -> SyntaxValidation:
        """Verifica erros comuns de sintaxe DAX."""
        expr_upper = expression.upper()
        
        # Verifica VAR sem RETURN
        if "VAR " in expr_upper and "RETURN " not in expr_upper:
            return SyntaxValidation(
                is_valid=False,
                error_message="Declaração VAR sem RETURN correspondente"
            )
        
        # Verifica RETURN sem VAR
        if "RETURN " in expr_upper and "VAR " not in expr_upper:
            # Pode ser válido em alguns contextos, mas é suspeito
            logger.debug("RETURN encontrado sem VAR - pode ser intencional")
        
        # Verifica vírgulas duplicadas
        if ",," in expression.replace(" ", ""):
            return SyntaxValidation(
                is_valid=False,
                error_message="Vírgulas duplicadas encontradas"
            )
        
        # Verifica operadores duplicados
        for op in ["++", "--", "**", "//"]:
            if op in expression.replace(" ", ""):
                return SyntaxValidation(
                    is_valid=False,
                    error_message=f"Operador duplicado encontrado: {op}"
                )
        
        return SyntaxValidation(is_valid=True)
    
    def get_function_signature(self, function_name: str) -> Optional[str]:
        """
        Retorna a assinatura de uma função DAX.
        
        Args:
            function_name: Nome da função.
            
        Returns:
            Assinatura da função ou None se não conhecida.
        """
        # TODO: Implementar dicionário de assinaturas
        signatures = {
            "CALCULATE": "CALCULATE(<Expression>[, <Filter1>[, <Filter2>[, ...]]])",
            "SUM": "SUM(<Column>)",
            "SUMX": "SUMX(<Table>, <Expression>)",
            "FILTER": "FILTER(<Table>, <FilterExpression>)",
            "IF": "IF(<Condition>, <TrueResult>[, <FalseResult>])",
            "SWITCH": "SWITCH(<Expression>, <Value1>, <Result1>[, <Value2>, <Result2>[, ...]][, <Else>])",
        }
        
        return signatures.get(function_name.upper())
