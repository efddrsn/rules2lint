import concurrent.futures
import os
import traceback
from tqdm import tqdm
from config import KEYWORD_TEMPLATES, MAX_WORKERS
from llm_interactions import llm_extract_flags

def generate_eslint_config_object(term, context, rule_text):
    """Generates a single ESLint config object based on the term, context, and template."""
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
        return config_object
    except Exception as e:
         tqdm.write(f"Error applying template for term '{term}' (context: {context}) from rule '{rule_text}': {e}")
         return None # Indicate failure

def process_refined_rule(client, rule_text):
    """
    Processes a single refined rule: extracts flags and generates ESLint configs.
    Returns a list of tuples: [(severity, config_object), ...].
    """
    extracted_flags = llm_extract_flags(client, rule_text)
    generated_configs = []

    if not extracted_flags:
        return [] # Return empty list if LLM returns no flags or errors

    for flag in extracted_flags:
        term = flag.get("term")
        context = flag.get("context", "Unknown")
        severity = flag.get("severity", "warn") # Default to warn

        if not term:
            tqdm.write(f"Warning: Flag missing 'term' in response for rule '{rule_text}'. Flag: {flag}")
            continue

        config_object = generate_eslint_config_object(term, context, rule_text)
        if config_object:
            generated_configs.append((severity, config_object))

    return generated_configs

def run_parallel_rule_processing(client, refined_rules):
    """
    Processes refined rules in parallel to extract flags and generate configs.
    Returns a list of all generated (severity, config_object) tuples.
    """
    print(f"\nProcessing {len(refined_rules)} final rules in parallel to extract flags...")
    all_flag_configs = [] # Will store tuples of (severity, config_object)
    futures = []
    # Adjust num_workers based on typical LLM API latency vs CPU overhead
    num_workers = min(MAX_WORKERS, (os.cpu_count() or 1) + 4)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit tasks
        for rule_text in refined_rules: # Use refined list
            futures.append(executor.submit(process_refined_rule, client, rule_text))

        print("\nExtracting flags and generating configs...")
        # Process results as they complete
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(refined_rules), desc="Extracting Flags", unit="rule", position=0, leave=True):
            try:
                # process_refined_rule returns a list of (severity, config_object) tuples
                result_list = future.result()
                if result_list:
                    all_flag_configs.extend(result_list)
            except Exception as exc:
                # Log the error
                tqdm.write(f'\nError retrieving result from future: {exc}')
                tb_str = traceback.format_exc()
                tqdm.write(f"Traceback:\n{tb_str}")

    return all_flag_configs

def aggregate_eslint_configs(all_flag_configs):
    """
    Aggregates individual flag configs into the final ESLint structure for 'no-restricted-syntax'.
    Returns the final rules object and the highest severity level.
    """
    print(f"\nFinished processing. Aggregating {len(all_flag_configs)} flag configurations...")

    # Build the final rules object for no-restricted-syntax
    combined_syntax_configs = []
    highest_severity = "warn" # Start with warn

    # Combine configs, ensuring no duplicates and tracking highest severity
    seen_selectors = set()
    for severity, config in all_flag_configs:
        selector = config.get("selector")
        # Ensure config is a dictionary before proceeding
        if isinstance(config, dict) and selector and selector not in seen_selectors:
            combined_syntax_configs.append(config)
            seen_selectors.add(selector)
            if severity == "error":
                highest_severity = "error" # Elevate overall severity if any flag is error
        elif not isinstance(config, dict):
             tqdm.write(f"Warning: Skipping invalid config object during aggregation: {config}")


    final_rules_object = {}
    rule_count = 0
    if combined_syntax_configs:
         # Format for no-restricted-syntax: [severity, option1, option2, ...]
         final_rules_object["no-restricted-syntax"] = [highest_severity] + combined_syntax_configs
         rule_count = len(combined_syntax_configs)

    return final_rules_object, highest_severity, rule_count 