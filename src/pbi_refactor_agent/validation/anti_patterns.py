"""
Detector de Anti-Patterns DAX.

Analisa expressoes DAX em busca de padroes problematicos e sugere
melhorias baseadas em best practices de Power BI.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class Severity(str, Enum):
    """Severidade do anti-pattern."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class AntiPatternFinding:
    """Um anti-pattern encontrado em uma expressao DAX."""
    rule_id: str
    rule_name: str
    severity: Severity
    message: str
    suggestion: str
    measure_name: str = ""
    table_name: str = ""
    snippet: str = ""


@dataclass
class AntiPatternReport:
    """Relatorio completo de anti-patterns de um modelo."""
    findings: list[AntiPatternFinding] = field(default_factory=list)
    total_measures_analyzed: int = 0

    @property
    def total_findings(self) -> int:
        return len(self.findings)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def infos(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.INFO)

    @property
    def score(self) -> float:
        """Score de qualidade de 0 a 100."""
        if self.total_measures_analyzed == 0:
            return 100.0
        penalty = self.errors * 10 + self.warnings * 3 + self.infos * 1
        raw = max(0, 100 - penalty)
        return round(raw, 1)


class AntiPatternDetector:
    """
    Detecta anti-patterns em expressoes DAX.

    Regras implementadas:
    - AP01: Divisao com / em vez de DIVIDE()
    - AP02: IF aninhados (sugerir SWITCH)
    - AP03: Ausencia de VAR em expressoes complexas
    - AP04: CALCULATE sem filtro explicito
    - AP05: Iteradores sobre tabela inteira sem filtro
    - AP06: Uso de FILTER(ALL(...)) em vez de KEEPFILTERS
    - AP07: Expressao vazia ou trivial
    - AP08: Referencia circular potencial
    - AP09: FORMAT em medida (impacto em performance)
    - AP10: Uso de COUNTROWS(FILTER(...)) em vez de CALCULATE + COUNTROWS
    - AP11: Medidas sem descricao (BPA)
    - AP12: Nomes nao padronizados com espacos (BPA)
    - AP13: ALL() sem especificacao de coluna/tabela (BPA)
    - AP14: CALCULATEs aninhados desnecessarios (BPA)
    - AP15: SELECTEDVALUE sem valor padrao (BPA)
    - AP16: Uso de OR em vez de IN para multiplas comparacoes (BPA)
    - AP17: ISBLANK em vez de comparacao direta (BPA)
    - AP18: Iteradores X quando agregacao simples seria suficiente (BPA)
    """

    def analyze_model(self, metadata) -> AntiPatternReport:
        """
        Analisa todas as medidas de um ModelMetadata.

        Args:
            metadata: ModelMetadata extraido do .pbit.

        Returns:
            AntiPatternReport com todos os achados.
        """
        report = AntiPatternReport()

        for table in metadata.business_tables:
            for measure in table.measures:
                if not measure.expression:
                    continue
                report.total_measures_analyzed += 1
                findings = self._analyze_expression(
                    expression=measure.expression,
                    measure_name=measure.name,
                    table_name=table.name,
                )
                report.findings.extend(findings)
                
                # Regras que dependem de metadados (nao apenas da expressao)
                findings.extend(self._analyze_measure_metadata(measure, table.name))

        logger.info(
            "Analise de anti-patterns concluida",
            measures=report.total_measures_analyzed,
            findings=report.total_findings,
        )
        return report

    def _analyze_expression(
        self,
        expression: str,
        measure_name: str = "",
        table_name: str = "",
    ) -> list[AntiPatternFinding]:
        """Aplica todas as regras a uma expressao."""
        findings = []
        rules = [
            self._ap01_division_without_divide,
            self._ap02_nested_if,
            self._ap03_missing_var,
            self._ap04_calculate_without_filter,
            self._ap05_iterator_without_filter,
            self._ap06_filter_all,
            self._ap07_empty_expression,
            self._ap09_format_in_measure,
            self._ap10_countrows_filter,
            self._ap13_all_without_specification,
            self._ap14_nested_calculates,
            self._ap15_selectedvalue_without_default,
            self._ap16_or_instead_of_in,
            self._ap17_isblank_comparison,
            self._ap18_iterator_instead_of_aggregation,
        ]
        for rule in rules:
            result = rule(expression)
            if result:
                result.measure_name = measure_name
                result.table_name = table_name
                findings.append(result)
        return findings
    
    def _analyze_measure_metadata(self, measure, table_name: str) -> list[AntiPatternFinding]:
        """Analisa metadados da medida (nome, descricao, etc)."""
        findings = []
        
        # AP11: Medida sem descricao
        if not measure.description or not measure.description.strip():
            findings.append(AntiPatternFinding(
                rule_id="AP11",
                rule_name="Medida sem descricao",
                severity=Severity.INFO,
                message="Medida nao possui descricao documentada.",
                suggestion="Adicione uma descricao clara da logica de negocio desta medida.",
                measure_name=measure.name,
                table_name=table_name,
            ))
        
        # AP12: Nome nao padronizado (espacos)
        if ' ' in measure.name:
            findings.append(AntiPatternFinding(
                rule_id="AP12",
                rule_name="Nome com espacos",
                severity=Severity.INFO,
                message="Nome da medida contem espacos. Dificulta referencia em expressoes.",
                suggestion="Use PascalCase ou snake_case: 'TotalVendas' ou 'Total_Vendas'.",
                measure_name=measure.name,
                table_name=table_name,
            ))
        
        return findings

    # -- Regras --

    def _ap01_division_without_divide(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta divisao com / em vez de DIVIDE()."""
        # Remove strings e comentarios
        clean = re.sub(r'"[^"]*"', '', expr)
        clean = re.sub(r'//.*$', '', clean, flags=re.MULTILINE)
        # Procura / que nao esta dentro de URL ou comentario
        if re.search(r'(?<![/:])\s*/\s*(?![/*])', clean):
            # Verifica se ja usa DIVIDE
            if 'DIVIDE' not in expr.upper():
                return AntiPatternFinding(
                    rule_id="AP01",
                    rule_name="Divisao sem DIVIDE()",
                    severity=Severity.WARNING,
                    message="Uso de operador / para divisao. Risco de erro por divisao por zero.",
                    suggestion="Substitua A / B por DIVIDE(A, B) ou DIVIDE(A, B, 0).",
                    snippet=expr[:80],
                )
        return None

    def _ap02_nested_if(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta IFs aninhados (3+) e sugere SWITCH."""
        upper = expr.upper()
        if_count = len(re.findall(r'\bIF\s*\(', upper))
        if if_count >= 3:
            return AntiPatternFinding(
                rule_id="AP02",
                rule_name="IF aninhados",
                severity=Severity.WARNING,
                message=f"{if_count} IFs aninhados detectados. Reduz legibilidade e manutencao.",
                suggestion="Considere usar SWITCH(TRUE(), ...) para multiplas condicoes.",
            )
        return None

    def _ap03_missing_var(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta expressoes complexas sem uso de VAR."""
        upper = expr.upper()
        # So aplica para expressoes com mais de 100 chars
        if len(expr) < 100:
            return None
        if 'VAR ' not in upper and 'RETURN' not in upper:
            func_count = len(re.findall(r'[A-Z_]+\s*\(', upper))
            if func_count >= 3:
                return AntiPatternFinding(
                    rule_id="AP03",
                    rule_name="Ausencia de VAR",
                    severity=Severity.INFO,
                    message=f"Expressao complexa ({func_count} funcoes) sem uso de variaveis (VAR/RETURN).",
                    suggestion="Use VAR para armazenar calculos intermediarios. Melhora legibilidade e pode melhorar performance.",
                )
        return None

    def _ap04_calculate_without_filter(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta CALCULATE sem argumento de filtro."""
        # Encontra CALCULATE( com apenas um argumento (sem virgula apos o primeiro arg)
        matches = re.finditer(r'\bCALCULATE\s*\(', expr, re.IGNORECASE)
        for match in matches:
            start = match.end()
            depth = 1
            pos = start
            has_comma = False
            while pos < len(expr) and depth > 0:
                if expr[pos] == '(':
                    depth += 1
                elif expr[pos] == ')':
                    depth -= 1
                elif expr[pos] == ',' and depth == 1:
                    has_comma = True
                    break
                pos += 1
            if not has_comma and depth == 0:
                return AntiPatternFinding(
                    rule_id="AP04",
                    rule_name="CALCULATE sem filtro",
                    severity=Severity.WARNING,
                    message="CALCULATE usado sem argumento de filtro. O CALCULATE sem filtro e redundante.",
                    suggestion="Remova o CALCULATE ou adicione um filtro explicito como segundo argumento.",
                )
        return None

    def _ap05_iterator_without_filter(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta iteradores sobre tabela inteira sem filtro."""
        iterators = ["SUMX", "AVERAGEX", "COUNTX", "MAXX", "MINX", "RANKX", "CONCATENATEX"]
        upper = expr.upper()
        for it in iterators:
            pattern = rf'\b{it}\s*\(\s*[\'"]?[A-Za-z_]+[\'"]?\s*,'
            if re.search(pattern, upper):
                # Checa se nao tem FILTER/TOPN envolvendo a tabela
                if 'FILTER' not in upper and 'TOPN' not in upper:
                    return AntiPatternFinding(
                        rule_id="AP05",
                        rule_name="Iterador sem filtro",
                        severity=Severity.INFO,
                        message=f"{it} itera sobre a tabela inteira. Pode ser lento em tabelas grandes.",
                        suggestion=f"Considere filtrar a tabela antes de iterar: {it}(FILTER(...), ...).",
                    )
        return None

    def _ap06_filter_all(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta FILTER(ALL(...))."""
        if re.search(r'\bFILTER\s*\(\s*ALL\s*\(', expr, re.IGNORECASE):
            return AntiPatternFinding(
                rule_id="AP06",
                rule_name="FILTER(ALL(...))",
                severity=Severity.INFO,
                message="Padrao FILTER(ALL(...)) detectado. Pode ser substituido por abordagem mais eficiente.",
                suggestion="Considere usar CALCULATE com REMOVEFILTERS() ou KEEPFILTERS() dependendo do caso.",
            )
        return None

    def _ap07_empty_expression(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta expressao vazia ou trivial."""
        stripped = expr.strip()
        if not stripped:
            return AntiPatternFinding(
                rule_id="AP07",
                rule_name="Expressao vazia",
                severity=Severity.ERROR,
                message="Medida com expressao DAX vazia.",
                suggestion="Adicione uma expressao DAX valida.",
            )
        # Expressao trivial: apenas um literal
        if re.match(r'^[\d.]+$', stripped) or stripped in ('""', 'BLANK()'):
            return AntiPatternFinding(
                rule_id="AP07",
                rule_name="Expressao trivial",
                severity=Severity.INFO,
                message=f"Medida com expressao trivial: {stripped}",
                suggestion="Verifique se esta medida e realmente necessaria.",
            )
        return None

    def _ap09_format_in_measure(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta uso de FORMAT() dentro de medida."""
        if re.search(r'\bFORMAT\s*\(', expr, re.IGNORECASE):
            return AntiPatternFinding(
                rule_id="AP09",
                rule_name="FORMAT em medida",
                severity=Severity.WARNING,
                message="FORMAT() converte numeros em texto, impedindo formatacao dinamica e afetando performance.",
                suggestion="Use Format String na propriedade da medida em vez de FORMAT() na expressao.",
            )
        return None

    def _ap10_countrows_filter(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta COUNTROWS(FILTER(...)) em vez de CALCULATE+COUNTROWS."""
        if re.search(r'\bCOUNTROWS\s*\(\s*FILTER\s*\(', expr, re.IGNORECASE):
            return AntiPatternFinding(
                rule_id="AP10",
                rule_name="COUNTROWS(FILTER(...))",
                severity=Severity.INFO,
                message="Padrao COUNTROWS(FILTER(...)) pode ser ineficiente.",
                suggestion="Considere CALCULATE(COUNTROWS(tabela), filtro) para melhor performance.",
            )
        return None

    # -- Novas Regras BPA (Best Practice Analyzer) --

    def _ap13_all_without_specification(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta ALL() sem especificacao de coluna ou tabela."""
        # Procura ALL() seguido de parenteses vazios ou apenas com virgula
        if re.search(r'\bALL\s*\(\s*\)', expr, re.IGNORECASE):
            return AntiPatternFinding(
                rule_id="AP13",
                rule_name="ALL() sem especificacao",
                severity=Severity.WARNING,
                message="ALL() sem argumentos remove todos os filtros do modelo. Pode ser perigoso.",
                suggestion="Especifique a tabela ou coluna: ALL(Tabela) ou ALL(Tabela[Coluna]).",
            )
        return None

    def _ap14_nested_calculates(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta CALCULATEs aninhados desnecessarios."""
        upper = expr.upper()
        # Procura CALCULATE dentro de outro CALCULATE
        if upper.count('CALCULATE') >= 2:
            # Verifica se ha aninhamento real
            if re.search(r'\bCALCULATE\s*\([^)]*\bCALCULATE\s*\(', expr, re.IGNORECASE):
                return AntiPatternFinding(
                    rule_id="AP14",
                    rule_name="CALCULATEs aninhados",
                    severity=Severity.WARNING,
                    message="CALCULATEs aninhados detectados. Reduz legibilidade e pode afetar performance.",
                    suggestion="Consolide os filtros em um unico CALCULATE ou use VAR para separar logicas.",
                )
        return None

    def _ap15_selectedvalue_without_default(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta SELECTEDVALUE sem valor padrao (segundo parametro)."""
        # Procura SELECTEDVALUE com apenas um argumento
        matches = re.finditer(r'\bSELECTEDVALUE\s*\(', expr, re.IGNORECASE)
        for match in matches:
            start = match.end()
            depth = 1
            pos = start
            comma_count = 0
            while pos < len(expr) and depth > 0:
                if expr[pos] == '(':
                    depth += 1
                elif expr[pos] == ')':
                    depth -= 1
                elif expr[pos] == ',' and depth == 1:
                    comma_count += 1
                pos += 1
            # Se nao tem virgula (apenas 1 argumento)
            if comma_count == 0:
                return AntiPatternFinding(
                    rule_id="AP15",
                    rule_name="SELECTEDVALUE sem padrao",
                    severity=Severity.INFO,
                    message="SELECTEDVALUE sem segundo parametro retorna BLANK() quando multiplos valores estao selecionados.",
                    suggestion="Adicione um valor padrao: SELECTEDVALUE(Coluna, \"Multiplos\") ou SELECTEDVALUE(Coluna, 0).",
                )
        return None

    def _ap16_or_instead_of_in(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta uso de OR quando IN seria mais adequado."""
        # Procura padroes como: coluna = valor1 || coluna = valor2 || ...
        pattern = r'(\w+\[[\w\s]+\]|\[[\w\s]+\])\s*=\s*[^|]+\|\|\s*\1\s*='
        if re.search(pattern, expr):
            return AntiPatternFinding(
                rule_id="AP16",
                rule_name="OR em vez de IN",
                severity=Severity.INFO,
                message="Multiplas comparacoes com OR (||) detectadas para mesma coluna.",
                suggestion="Use o operador IN para melhor legibilidade: Coluna IN {\"A\", \"B\", \"C\"}.",
            )
        return None

    def _ap17_isblank_comparison(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta ISBLANK quando comparacao direta seria mais clara."""
        if re.search(r'\bISBLANK\s*\([^)]+\)\s*=\s*(TRUE|FALSE)', expr, re.IGNORECASE):
            return AntiPatternFinding(
                rule_id="AP17",
                rule_name="ISBLANK com comparacao redundante",
                severity=Severity.INFO,
                message="Comparacao ISBLANK(...) = TRUE/FALSE e redundante.",
                suggestion="Use ISBLANK(...) diretamente ou NOT ISBLANK(...) para negacao.",
            )
        return None

    def _ap18_iterator_instead_of_aggregation(self, expr: str) -> Optional[AntiPatternFinding]:
        """Detecta iteradores X quando agregacao simples seria suficiente."""
        # Exemplo: SUMX(Tabela, Tabela[Coluna]) em vez de SUM(Tabela[Coluna])
        pattern = r'\b(SUMX|AVERAGEX|COUNTX|MINX|MAXX)\s*\(\s*[\w\'\"]+\s*,\s*[\w\'\"]+\[[\w\s]+\]\s*\)'
        match = re.search(pattern, expr, re.IGNORECASE)
        if match:
            iterator = match.group(1).upper()
            base_func = iterator.replace('X', '')  # SUMX -> SUM
            return AntiPatternFinding(
                rule_id="AP18",
                rule_name="Iterador desnecessario",
                severity=Severity.INFO,
                message=f"{iterator} usado para simples agregacao de coluna.",
                suggestion=f"Use {base_func}() diretamente: {base_func}(Tabela[Coluna]) e mais eficiente.",
            )
        return None
