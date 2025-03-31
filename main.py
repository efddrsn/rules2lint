import json
import os
# import subprocess # Removed
# import tempfile # Removed
import traceback
import concurrent.futures
from tqdm import tqdm
from openai import OpenAI
from dotenv import load_dotenv
import time
# import shutil # Removed
# import re # Removed

# Import modularized functions
from file_io import read_rules_file, write_eslint_config_file
from llm_interactions import llm_filter_rules, llm_refine_rule
from rule_processing import run_parallel_rule_processing, aggregate_eslint_configs

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client securely
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set.")
client = OpenAI(api_key=api_key)

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

def extract_flags(rule_text):
    """
    Calls OpenAI API to extract keywords/terms to flag from a rule description.
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
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0.1, # Low temperature for deterministic extraction
            timeout=45.0
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
        # tb_str = traceback.format_exc()
        # tqdm.write(f"Traceback:\n{tb_str}")
        return [] # Return empty list on error

# Function to process a single rule (extract flags, generate configs)
def process_rule(rule_text):
    """
    Extracts flags using LLM and generates ESLint config objects based on templates.
    Returns a list of tuples: [(severity, config_object), ...].
    """
    extracted_flags = extract_flags(rule_text)
    generated_configs = []

    if not extracted_flags:
        # tqdm.write(f"No flags extracted for rule: '{rule_text}'") # Optional log
        return [] # Return empty list if LLM returns no flags or errors

    for flag in extracted_flags:
        term = flag.get("term")
        context = flag.get("context", "Unknown")
        severity = flag.get("severity", "warn") # Default to warn

        if not term:
            tqdm.write(f"Warning: Flag missing 'term' in response for rule '{rule_text}'. Flag: {flag}")
            continue

        # Escape potential special characters in term for selector/message
        # Basic escaping for quotes; more complex terms might need more robust handling
        # Escape for JS strings in message first
        js_escaped_term = term.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
        js_escaped_rule_text = rule_text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

        # Escape differently for AST selectors (single quotes usually ok unless term contains them)
        selector_escaped_term = term.replace("'", "\\'") # Only escape single quotes for selector

        template_func = KEYWORD_TEMPLATES.get(context, KEYWORD_TEMPLATES["Unknown"])

        try:
            # Pass the differently escaped terms to the template function
            config_object = template_func(selector_escaped_term, js_escaped_rule_text)
            generated_configs.append((severity, config_object))
            # tqdm.write(f"DBG: Rule '{rule_text}' -> Flag '{term}' ({context}) -> Config: {config_object} Severity: {severity}") # Debug log
        except Exception as e:
             tqdm.write(f"Error applying template for flag {flag} from rule '{rule_text}': {e}")

    return generated_configs


def filter_lintable_rules(raw_lines):
    """Uses LLM to filter raw lines into lintable rules and non-rules."""
    # --- Keeping this function as it helps preprocess rules ---
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
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            timeout=60.0
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

def translate_or_refine_rule(rule_text):
    """Uses LLM to refine a potentially complex rule into simpler, more concrete rules."""
    # --- Keeping this function as it helps preprocess rules ---
    # print(f"DBG: Attempting to translate/refine rule: '{rule_text}'") # Optional Debug

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
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0.2, # Lower temperature for more deterministic translation
            timeout=60.0
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

        # print(f"DBG: Translation outcome for '{rule_text}': {outcome}") # Optional Debug
        return outcome, refined_list

    except Exception as e:
        tqdm.write(f"Error during rule translation/refinement for '{rule_text}': {e}")
        # Fallback: Assume rule is simple and pass it through
        return "passed_through", [rule_text]

# --- Setup Helper Functions ---

def ensure_gitignore(directory):
    """Ensures a .gitignore file exists with essential Python and .env entries."""
    gitignore_path = os.path.join(directory, ".gitignore")
    if not os.path.exists(gitignore_path):
        print(f"Creating {gitignore_path}...")
        content = """# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python

# Environments
.env
.venv
venv/
env/

# IDEs / Editors
.vscode/
.idea/
*.swp
*.swo
"""
        try:
            with open(gitignore_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Successfully created {gitignore_path} with default entries.")
        except IOError as e:
            print(f"Warning: Could not create {gitignore_path}: {e}")
    else:
        # Ensure .env is in existing gitignore
        try:
            with open(gitignore_path, 'r+', encoding='utf-8') as f:
                if ".env" not in f.read():
                    print(f"Adding .env to existing {gitignore_path}...")
                    f.seek(0, os.SEEK_END) # Go to end of file
                    if f.tell() > 0: # Check if file is not empty
                        # Add newline if file doesn't end with one
                        f.seek(f.tell() - 1, os.SEEK_SET)
                        if f.read(1) != '\n':
                            f.write("\n")
                    f.write("\n# Secrets\n.env\n")
        except IOError as e:
            print(f"Warning: Could not read/update {gitignore_path}: {e}")

def ensure_requirements(directory):
    """Ensures a requirements.txt file exists with necessary dependencies."""
    requirements_path = os.path.join(directory, "requirements.txt")
    dependencies = [
        "openai",    # Consider pinning version, e.g., openai>=1.0.0,<2.0.0
        "python-dotenv",
        "tqdm"
    ]
    if not os.path.exists(requirements_path):
        print(f"Creating {requirements_path}...")
        try:
            with open(requirements_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(dependencies) + "\n")
            print(f"Successfully created {requirements_path}. You can now install dependencies using:")
            print(f"  pip install -r {requirements_path}")
        except IOError as e:
            print(f"Warning: Could not create {requirements_path}: {e}")

def setup_environment():
    """Loads environment variables and initializes OpenAI client."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set.")
    client = OpenAI(api_key=api_key)
    return client

def main():
    start_time = time.time()

    # --- Setup ---
    try:
        client = setup_environment()
    except ValueError as e:
        print(f"Error setting up environment: {e}")
        return

    # Determine paths
    script_dir = os.path.dirname(os.path.abspath(__file__)) # Directory containing main.py (rules2lint/)
    project_root_dir = os.path.dirname(script_dir)       # Parent directory (project root)

    # --- Ensure setup files exist in the script's directory (rules2lint/) ---
    ensure_gitignore(script_dir)
    ensure_requirements(script_dir)
    # --- End Ensure setup files ---

    rules_filepath = os.path.join(script_dir, '.cursorrules')
    output_filename = 'eslint.config.mjs'
    output_filepath = os.path.join(project_root_dir, output_filename) # Write config to project root
    print(f"INFO: Target ESLint config path: {output_filepath}") # Add info log

    # --- Read Rules ---
    try:
        raw_rules_lines = read_rules_file(rules_filepath)
        if not raw_rules_lines:
            print(f"Warning: {rules_filepath} file is empty or contains only whitespace.")
            return
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return
    except IOError as e:
        print(f"Error: {e}")
        return

    # --- Filter Rules ---
    lintable_rules, filtered_out_lines = llm_filter_rules(client, raw_rules_lines)

    if filtered_out_lines:
        print("\nThe following lines were filtered out as non-lintable rules:")
        for line in filtered_out_lines:
            if line:
                print(f"  - '{line}'")

    if not lintable_rules:
        print("\nNo potentially lintable rules found after filtering. Exiting.")
        return

    # --- Refine Rules ---
    print(f"\nRefining {len(lintable_rules)} potentially lintable rules...")
    refined_rules = []
    untranslated_rules = []
    # Process refinement sequentially for clearer logging before parallel generation
    for rule in tqdm(lintable_rules, desc="Refining rules", unit="rule"):
        try:
            outcome, rules_to_process = llm_refine_rule(client, rule)
            if outcome == "passed_through":
                refined_rules.extend(rules_to_process)
            elif outcome == "translated":
                tqdm.write(f"Rule '{rule}' was translated into {len(rules_to_process)} sub-rules:")
                for sub_rule in rules_to_process:
                    tqdm.write(f"  - {sub_rule}")
                refined_rules.extend(rules_to_process)
            else: # untranslatable
                tqdm.write(f"Rule marked as untranslatable: '{rule}'")
                untranslated_rules.append(rule)
        except Exception as e:
            tqdm.write(f"Error during refinement processing for rule '{rule}': {e}. Skipping rule.")
            untranslated_rules.append(rule) # Treat errors during refinement as untranslatable

    if untranslated_rules:
        print("\nThe following rules could not be translated into concrete checks or caused errors:")
        for rule in untranslated_rules:
            print(f"  - '{rule}'")

    if not refined_rules:
        print("\nNo rules remaining after translation/refinement step. Exiting.")
        return

    # --- Process Refined Rules (Parallel Flag Extraction) ---
    all_flag_configs = run_parallel_rule_processing(client, refined_rules)

    # --- Aggregate Configs ---
    final_rules_object, highest_severity, rule_count = aggregate_eslint_configs(all_flag_configs)

    # --- Write Output File ---
    write_eslint_config_file(
        output_filepath,
        final_rules_object,
        highest_severity,
        rule_count,
        len(refined_rules), # Pass count of processed rules
        untranslated_rules # Pass list of untranslated rules for reporting
    )

    # --- Finish ---
    end_time = time.time()
    print(f"\nTotal execution time: {end_time - start_time:.2f} seconds.")


if __name__ == "__main__":
    main()