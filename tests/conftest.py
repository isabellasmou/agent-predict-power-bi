"""
Fixtures compartilhados para testes pytest.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_mcp_client():
    """MCP Client mockado para testes."""
    client = AsyncMock()
    
    # Mock para listar tabelas
    client.list_tables = AsyncMock(return_value=[
        {"name": "Sales", "type": "table"},
        {"name": "Products", "type": "table"},
        {"name": "Date", "type": "table"},
    ])
    
    # Mock para obter medidas
    client.get_measures = AsyncMock(return_value=[
        {
            "name": "Total Sales",
            "table": "Sales",
            "expression": "SUM('Sales'[Amount])"
        },
        {
            "name": "Total Quantity",
            "table": "Sales",
            "expression": "SUM('Sales'[Quantity])"
        }
    ])
    
    # Mock para obter colunas
    client.get_columns = AsyncMock(return_value=[
        {"name": "Amount", "table": "Sales", "dataType": "decimal"},
        {"name": "Quantity", "table": "Sales", "dataType": "int"},
        {"name": "OrderID", "table": "Sales", "dataType": "int"},
    ])
    
    # Mock para conexão
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_connected = True
    
    return client


@pytest.fixture
def mock_settings():
    """Settings mockadas para testes."""
    settings = MagicMock()
    settings.openai_api_key = "sk-test-key"
    settings.anthropic_api_key = ""
    settings.azure_openai_api_key = ""
    settings.llm_provider = "openai"
    settings.openai_model = "gpt-4o"
    settings.max_retries = 3
    settings.timeout = 30
    settings.log_level = "DEBUG"
    return settings


@pytest.fixture
def sample_dax_expressions():
    """Expressões DAX de exemplo para testes."""
    return {
        "simple_sum": "SUM('Sales'[Amount])",
        "with_filter": "CALCULATE(SUM('Sales'[Amount]), 'Sales'[Region] = \"North\")",
        "with_var": """
VAR TotalSales = SUM('Sales'[Amount])
VAR TotalQty = SUM('Sales'[Quantity])
RETURN
    DIVIDE(TotalSales, TotalQty)
        """,
        "complex": """
CALCULATE(
    SUMX(
        FILTER('Sales', 'Sales'[Status] = "Active"),
        'Sales'[Amount] * 'Sales'[Discount]
    ),
    USERELATIONSHIP('Date'[DateKey], 'Sales'[OrderDate]),
    ALL('Products')
)
        """,
        "time_intelligence": """
VAR CurrentSales = [Total Sales]
VAR PreviousPeriod = CALCULATE([Total Sales], DATEADD('Date'[Date], -1, YEAR))
RETURN
    DIVIDE(CurrentSales - PreviousPeriod, PreviousPeriod)
        """,
    }


@pytest.fixture
def sample_model_schema():
    """Schema de modelo semântico de exemplo."""
    return {
        "tables": [
            {
                "name": "Sales",
                "columns": [
                    {"name": "SalesID", "dataType": "int", "isKey": True},
                    {"name": "Amount", "dataType": "decimal"},
                    {"name": "Quantity", "dataType": "int"},
                    {"name": "ProductID", "dataType": "int"},
                    {"name": "CustomerID", "dataType": "int"},
                    {"name": "OrderDate", "dataType": "datetime"},
                ],
                "measures": [
                    {
                        "name": "Total Sales",
                        "expression": "SUM('Sales'[Amount])",
                        "description": "Soma total de vendas"
                    },
                    {
                        "name": "Total Quantity",
                        "expression": "SUM('Sales'[Quantity])",
                        "description": "Quantidade total vendida"
                    },
                    {
                        "name": "Average Sale",
                        "expression": "AVERAGE('Sales'[Amount])",
                        "description": "Média por transação"
                    }
                ]
            },
            {
                "name": "Products",
                "columns": [
                    {"name": "ProductID", "dataType": "int", "isKey": True},
                    {"name": "ProductName", "dataType": "string"},
                    {"name": "Category", "dataType": "string"},
                    {"name": "Price", "dataType": "decimal"},
                ],
                "measures": [
                    {
                        "name": "Product Count",
                        "expression": "COUNTROWS('Products')",
                        "description": "Total de produtos"
                    }
                ]
            },
            {
                "name": "Date",
                "columns": [
                    {"name": "Date", "dataType": "datetime", "isKey": True},
                    {"name": "Year", "dataType": "int"},
                    {"name": "Month", "dataType": "int"},
                    {"name": "Quarter", "dataType": "string"},
                ],
                "measures": []
            }
        ],
        "relationships": [
            {
                "name": "Sales_to_Products",
                "fromTable": "Sales",
                "fromColumn": "ProductID",
                "toTable": "Products",
                "toColumn": "ProductID"
            },
            {
                "name": "Sales_to_Date",
                "fromTable": "Sales",
                "fromColumn": "OrderDate",
                "toTable": "Date",
                "toColumn": "Date"
            }
        ]
    }
