# Configuration constants for rules2lint generation

# Define templates for no-restricted-syntax based on context
# Using simplified selectors for broader matching initially
KEYWORD_TEMPLATES = {
    "Identifier": lambda kw, rule: {"selector": f"Identifier[name='{kw}']", "message": f"Usage of identifier '{kw}' is restricted by rule: {rule}"},
    "Literal": lambda kw, rule: {"selector": f"Literal[value='{kw}']", "message": f"Usage of literal '{kw}' is restricted by rule: {rule}"},
    "Operator": lambda kw, rule: {"selector": f":matches(BinaryExpression, LogicalExpression)[operator='{kw}']", "message": f"Usage of operator '{kw}' is restricted by rule: {rule}"},
    "Keyword": lambda kw, rule: {"selector": f"{kw.capitalize()}Statement", "message": f"Usage of keyword '{kw}' is restricted by rule: {rule}"}, # Basic guess for keywords like 'try', 'var'
    "Property": lambda kw, rule: {"selector": f"MemberExpression[property.name='{kw}']", "message": f"Usage of property '{kw}' is restricted by rule: {rule}"},
    "Import": lambda kw, rule: {"selector": f"ImportDeclaration[source.value='{kw}']", "message": f"Import from '{kw}' is restricted by rule: {rule}"},
    # Default/fallback template
    "Unknown": lambda kw, rule: {"selector": f":matches(Identifier[name='{kw}'], Literal[value='{kw}'])", "message": f"Usage of '{kw}' is restricted by rule: {rule} (context unknown)"}
}

# Potentially add other constants here later, like model names, timeouts, etc.
MODEL_NAME_FILTER = "gpt-4o"
MODEL_NAME_REFINE = "gpt-4o"
MODEL_NAME_EXTRACT = "gpt-4o"
API_TIMEOUT_FILTER = 60.0
API_TIMEOUT_REFINE = 60.0
API_TIMEOUT_EXTRACT = 45.0
MAX_WORKERS = 8 