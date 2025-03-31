import json
from tqdm import tqdm
from config import MODEL_NAME_FILTER, API_TIMEOUT_FILTER, MODEL_NAME_REFINE, API_TIMEOUT_REFINE, MODEL_NAME_EXTRACT, API_TIMEOUT_EXTRACT

def llm_filter_rules(client, raw_lines):
    """Uses LLM to filter raw lines into lintable rules and non-rules."""
    print("\nFiltering rules using LLM (inclusive approach)...")
    input_text = "\n".join(raw_lines)

    prompt = f"""
Analyze the following lines from a rule configuration file. Your goal is to identify lines that express **any** preference, constraint, style guide, naming convention, or prohibition that could **potentially** be enforced by a linter like ESLint by **flagging specific keywords, literals, operators or patterns**. Assume users may not phrase rules perfectly.

**Bias towards including lines unless they are clearly NOT rules or cannot be mapped to specific flags.**

Consider these types as potentially lintable:
1.  Direct style rules involving specific operators/keywords (e.g., "Use === instead of ==")
2.  Naming conventions (e.g., "Function names must be camelCase") -> Might be hard for keyword flagging, but include for now.
3.  Prohibitions on specific keywords, functions, patterns, or practices (e.g., "Do NOT hardcode anything", "No fallbacks", "Avoid Math.random()").
4.  Lines stating specific values or facts (e.g., `Pinecone index: nomic-property-embeddings`, `Latest model: gpt-4o`). Assume these imply a rule related to that value (e.g., flag other values, flag this value).

Filter out **ONLY** lines that are:
-   Clearly comments (e.g., starting with # or //).
-   Empty lines.
-   Section headers or purely organizational text (e.g., `Information:`, `Iteration Guidelines:`).
-   Extremely vague, subjective, or un-lintable advice that **cannot** be reduced to flagging specific terms (e.g., "write good code", "be careful", "Tests should be easy to understand").
-   Instructions directed at humans/AI assistants, not code (e.g., "Always validate with the user").

Return the results as a JSON object with two keys:
- "lintable_rules": A list of strings, where each string is a line identified as a potentially lintable rule according to the inclusive criteria above.
- "filtered_out": A list of strings, containing only the lines that were clearly filtered out based on the strict exclusion criteria.

Example Input Lines:
# Use strict equality
Use === instead of ==
- Do NOT hardcode anything
Information:
Latest OPENAI model is "gpt-4o"
Write clear variable names
No console.log statements allowed
ALWAYS VALIDATE implementation with the USER

Example JSON Output:
{{
  "lintable_rules": [
    "Use === instead of ==",
    "- Do NOT hardcode anything",
    "Latest OPENAI model is \"gpt-4o\"",
    "No console.log statements allowed"
  ],
  "filtered_out": [
    "# Use strict equality",
    "",
    "Information:",
    "Write clear variable names",
    "ALWAYS VALIDATE implementation with the USER"
  ]
}}

Input Lines:
---
{input_text}
---

Respond ONLY with the JSON object.
"""

    json_schema = {
        "name": "filtered_rules_response",
        "schema": {
            "type": "object",
            "properties": {
                "lintable_rules": {"type": "array", "items": {"type": "string"}},
                "filtered_out": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["lintable_rules", "filtered_out"]
        }
    }

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME_FILTER,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            timeout=API_TIMEOUT_FILTER
        )
        result_json = json.loads(response.choices[0].message.content)
        lintable = result_json.get("lintable_rules", [])
        filtered = result_json.get("filtered_out", [])
        print(f"LLM filtering complete. Found {len(lintable)} potential rules.")
        return lintable, filtered
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        print(f"Error parsing LLM filter response: {e}. Proceeding without filtering.")
        return raw_lines, [] # Fallback: treat all lines as lintable, none filtered
    except Exception as e:
        print(f"Error calling OpenAI API for filtering: {e}. Proceeding without filtering.")
        return raw_lines, [] # Fallback

def llm_refine_rule(client, rule_text):
    """Uses LLM to refine a potentially complex rule into simpler, more concrete rules."""
    prompt = f"""
Analyze the input coding rule.

Determine if the rule is:
a) Simple and directly actionable by flagging specific terms: Describes a specific keyword, function name, variable name, literal, or operator (e.g., 'Use === instead of ==', 'No console.log', 'Avoid Math.random', 'Disallow "SECRET_KEY"').
b) Complex or Abstract: Describes a broader principle or prohibition that might require translation into specific terms to flag (e.g., 'Do NOT hardcode anything', 'No mock data', 'Tests should not reimplement core logic', 'Latest model is gpt-4o').

Your Task:
1.  If the rule is **Simple (a)**, return it unchanged.
2.  If the rule is **Complex/Abstract (b)**, attempt to break it down into ONE or MORE simpler rules, where *each simpler rule focuses on a specific term* (keyword, literal, identifier, operator) that should be flagged.
    *   **Focus on tangible terms**: "fallback", "mock", "==", "||", "random", "SECRET_KEY", "/mocks/", "try".
    *   **Example Breakdown**:
        - 'Do NOT hardcode anything' -> ["Disallow literals matching credential patterns like 'KEY'", "Disallow literals matching credential patterns like 'SECRET'", "Disallow magic numbers like 500 or 1000"].
        - 'Latest OPENAI model is "gpt-4o"' -> ["Flag string literal 'gpt-4o' (to potentially warn for non-latest usage)", "Flag string literal 'gpt-3.5-turbo'", "Flag string literal 'gpt-4'"].
        - 'WE DONT USE MOCK DATA' -> ["Disallow imports from paths containing '/mocks/'", "Disallow imports from paths containing '/fixtures/'", "Flag variables named 'mockData'", "Flag variables named 'dummyData'"].
        - 'WE DONT USE REGEX FOR PATTERN FINDING. WE USE LLMs' -> ["Disallow usage of the 'RegExp' constructor", "Disallow regex literals like '/.../'"].
        - 'WE DONT USE FALLBACKS. EVER.' -> ["Disallow the '||' operator", "Disallow the '??' operator", "Disallow empty 'catch' blocks (keyword 'try')", "Disallow identifiers named 'fallback'"]
3.  If a Complex/Abstract rule **cannot be reasonably broken down** into concrete terms to flag, indicate it is untranslatable.

Output Format:
Return ONLY a JSON object with the following keys:
- "outcome": A string, either "passed_through" (for simple rules), "translated" (if successfully broken down), or "untranslatable".
- "refined_rules": A list of strings. Contains the original rule if "outcome" is "passed_through", or the list of new, simpler rule strings if "outcome" is "translated", or an empty list if "outcome" is "untranslatable". Each refined rule should ideally focus on one specific term/pattern to flag.

Example 1:
Input Rule: "Use === instead of =="
Output: {{"outcome": "passed_through", "refined_rules": ["Use === instead of =="]}}

Example 2:
Input Rule: "Do not hardcode API keys"
Output: {{"outcome": "translated", "refined_rules": ["Disallow string literals containing 'KEY'", "Disallow string literals containing 'SECRET'", "Flag assignments to variables named 'apiKey'", "Flag assignments to variables named 'secretKey'"]}}

Example 3:
Input Rule: "Tests should be easy to understand"
Output: {{"outcome": "untranslatable", "refined_rules": []}}

Example 4:
Input Rule: "WE DONT USE FALLBACKS. EVER."
Output: {{"outcome": "translated", "refined_rules": ["Disallow the '||' operator", "Disallow the '??' operator", "Disallow empty 'catch' blocks", "Disallow identifiers named 'fallback'"]}}

Input Rule:
---
{rule_text}
---

Respond ONLY with the JSON object.
"""

    json_schema = {
        "name": "rule_translation_response",
        "schema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": ["passed_through", "translated", "untranslatable"]},
                "refined_rules": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["outcome", "refined_rules"]
        }
    }

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME_REFINE,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0.2, # Lower temperature for more deterministic translation
            timeout=API_TIMEOUT_REFINE
        )
        result_json = json.loads(response.choices[0].message.content)
        outcome = result_json.get("outcome", "untranslatable")
        refined_list = result_json.get("refined_rules", [])

        # Basic validation of response structure
        if outcome == "passed_through" and not refined_list:
            refined_list = [rule_text] # Ensure original rule is passed
        elif outcome == "translated" and not refined_list:
            outcome = "untranslatable" # If translated but list is empty, mark untranslatable
        elif outcome == "untranslatable":
             refined_list = [] # Ensure list is empty

        return outcome, refined_list

    except Exception as e:
        tqdm.write(f"Error during rule translation/refinement for '{rule_text}': {e}")
        # Fallback: Assume rule is simple and pass it through
        return "passed_through", [rule_text]

def llm_extract_flags(client, rule_text):
    """
    Calls OpenAI API to extract keywords/terms to flag from a rule description.
    Returns a list of flag objects or an empty list on error/no flags.
    """
    prompt = f"""
Analyze the following coding rule text. Your task is to identify specific keywords, string literals, operators, or patterns that should be flagged in code using ESLint's `no-restricted-syntax`.

Input Rule: "{rule_text}"

Instructions:
1.  Identify **specific, concrete terms** (keywords, variable names, function names, string literals, operators like '||', '??', '==') mentioned or clearly implied by the rule that should be disallowed or warned against.
2.  For each term, determine its most likely **syntactic context**:
    *   `Identifier`: A variable name, function name, object key (e.g., `fallback`, `mockData`, `Math`).
    *   `Literal`: A specific string or number value (e.g., `"SECRET_KEY"`, `500`, `"gpt-3.5-turbo"`).
    *   `Operator`: A comparison, logical, or assignment operator (e.g., `==`, `||`, `??`).
    *   `Keyword`: A JavaScript language keyword (e.g., `var`, `try`, `debugger`).
    *   `Property`: Accessing a property of an object (e.g., `random` in `Math.random`).
    *   `Import`: Importing from a specific path/module name.
    *   `Unknown`: If context is unclear or could be multiple things.
3.  Determine the intended **severity** based on the rule's phrasing:
    *   `error`: If the rule uses strong prohibition words (e.g., "MUST NOT", "NEVER", "DON'T", "DISALLOW", "NO").
    *   `warn`: If the rule uses softer suggestions (e.g., "AVOID", "PREFER NOT", "SHOULD NOT", "BE CAREFUL"). Default to `warn` if unclear.
4.  If the rule is too vague, abstract, or clearly cannot be enforced by flagging specific syntax elements (e.g., "write good code", "validate with user"), return an empty list.

Output Format:
Return ONLY a JSON object with a single key "flags". The value should be a list of objects, where each object represents a term to flag and has the following keys:
- "term": The specific keyword, literal, or operator string identified.
- "context": The determined syntactic context (e.g., "Identifier", "Literal", "Operator", "Keyword", "Property", "Import", "Unknown").
- "severity": The determined severity ("error" or "warn").

Example 1:
Input Rule: "WE DONT USE FALLBACKS. EVER."
Output: {{ "flags": [ {{ "term": "fallback", "context": "Identifier", "severity": "error" }}, {{ "term": "||", "context": "Operator", "severity": "error" }}, {{ "term": "??", "context": "Operator", "severity": "error" }} ] }}

Example 2:
Input Rule: "Avoid using Math.random()"
Output: {{ "flags": [ {{ "term": "random", "context": "Property", "severity": "warn" }} ] }}

Example 3:
Input Rule: "No mock data in production code."
Output: {{ "flags": [ {{ "term": "mock", "context": "Identifier", "severity": "error" }}, {{ "term": "dummy", "context": "Identifier", "severity": "error" }}, {{ "term": "/mocks/", "context": "Import", "severity": "error" }} ] }}

Example 4:
Input Rule: "Use === instead of =="
Output: {{ "flags": [ {{ "term": "==", "context": "Operator", "severity": "error" }} ] }}

Example 5:
Input Rule: "Latest model is gpt-4o"
Output: {{ "flags": [ {{ "term": "gpt-4o", "context": "Literal", "severity": "warn" }} ] }} # Assuming rule implies 'flag other models'

Example 6:
Input Rule: "Be careful when writing tests"
Output: {{ "flags": [] }}

Input Rule:
---
{rule_text}
---

Respond ONLY with the JSON object. Ensure the 'term' is accurately extracted (e.g., '==' not '===' if the rule is about banning '==').
"""

    json_schema = {
        "name": "extracted_flags_response",
        "schema": {
            "type": "object",
            "properties": {
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "term": {"type": "string"},
                            "context": {"type": "string", "enum": ["Identifier", "Literal", "Operator", "Keyword", "Property", "Import", "Unknown"]},
                            "severity": {"type": "string", "enum": ["error", "warn"]}
                        },
                        "required": ["term", "context", "severity"]
                    }
                }
            },
            "required": ["flags"]
        }
    }

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME_EXTRACT,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0.1, # Low temperature for deterministic extraction
            timeout=API_TIMEOUT_EXTRACT
        )
        result = json.loads(response.choices[0].message.content)
        # Basic validation
        if isinstance(result, dict) and "flags" in result and isinstance(result["flags"], list):
             return result["flags"]
        else:
            tqdm.write(f"Warning: LLM response for rule '{rule_text}' was malformed: {result}. Returning empty list.")
            return [] # Return empty list on malformed response

    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        tqdm.write(f"Error parsing LLM response for rule '{rule_text}': {e}. Response: {getattr(response, 'choices', [None])[0]}")
        return [] # Return empty list on error
    except Exception as e:
        tqdm.write(f"Error calling OpenAI API for rule '{rule_text}': {e}")
        return [] # Return empty list on error 