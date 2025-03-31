# rules2lint

<p align="center">
  <img src="./banner.png" alt="rules2lint banner" />
</p>

PROBLEM: .cursorrules and other natural language instructions are not enforceable, and LLMs often choose to ignore them.

SOLUTION: transform them into ESlint rules for automatic validation!

This tool converts custom coding rules from a `.cursorrules` file (located within the `rules2lint` folder) into an ESLint configuration file (`eslint.config.mjs`) using OpenAI's GPT-4o. The generated ESLint config is placed in the **parent directory** of `rules2lint`, allowing it to apply to your broader project.

## Files

```
rules2lint_project_root/
├── .cursorrules      # Your input rules file
├── .env              # Your OpenAI API Key (git ignored)
├── .gitignore        # Generated Git ignore file for this tool
├── LICENSE           # MIT License file for this tool
├── requirements.txt  # Generated Python dependencies for this tool
├── main.py           # Main script to run
├── config.py
├── file_io.py
├── llm_interactions.py
├── rule_processing.py
├── README.md         # This file
└── violation.js      # Example file for testing rules *within* this dir

# Generated output (example):
# ../eslint.config.mjs # << GENERATED IN PARENT DIR
```

## Setup
1. Ensure Python (3.7+) and **Node.js** (LTS version recommended, includes npm) are installed and accessible in your PATH.
2. Navigate into the `rules2lint` directory:
   ```bash
   cd path/to/your/project_root/rules2lint
   ```
3. Create a Python virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # or
   .venv\Scripts\activate  # Windows
   ```
4. Install Python dependencies:
   ```bash
   pip install openai python-dotenv tqdm
   ```
5. **Install ESLint in your main project:** The generated `eslint.config.mjs` is intended for use in the parent directory (your main project). Ensure ESLint is installed there:
   ```bash
   # Navigate to your main project directory (parent of rules2lint)
   cd path/to/your/project_root
   npm install eslint --save-dev
   ```
6. Create a `.env` file in the `rules2lint` directory and add your OpenAI API key:
   `OPENAI_API_KEY=your-api-key-here`
7. Create or move your `.cursorrules` file in the `rules2lint` directory with one rule per line (e.g., "No default parameters in functions") -- the model automatically filters out headings, comments, etc.
8. *Note:* When you run the script (see Usage below), it will automatically create `requirements.txt` and `.gitignore` within the `rules2lint` directory if they don't already exist.

## Usage
Run the main script from **within** the `rules2lint` directory:
```bash
cd path/to/your/project_root/rules2lint
python main.py
```
The script will:
- Ensure `.gitignore` and `requirements.txt` exist in the `rules2lint` directory (creating them if needed).
- Read rules from `.cursorrules` (in the `rules2lint` directory).
- Use the OpenAI API to process the rules.
- Generate an ESLint configuration based on the processed rules.
- Save the configuration to `eslint.config.mjs` in the **parent directory** (`project_root/`).

## How It Works
- The code is organized into several Python modules in the project root:
    - `main.py`: Orchestrates the rule processing workflow.
    - `config.py`: Stores configuration constants (API keys, model names, templates).
    - `file_io.py`: Handles reading the rules file and writing the ESLint config.
    - `llm_interactions.py`: Manages communication with the OpenAI API for filtering, refining, and extracting flags.
    - `rule_processing.py`: Contains logic for processing rules, generating ESLint configs based on templates, and handling parallel execution.
- Parses rules from `.cursorrules`.
- Loads OpenAI API key from `.env` file.
- Uses GPT-4o with structured JSON outputs to:
    - Filter potentially lintable rules.
    - Refine complex rules into simpler, flaggable terms.
    - Extract specific terms (keywords, literals, operators) and their context/severity.
- Uses `concurrent.futures` to process refined rules in parallel for flag extraction.
- Generates ESLint `no-restricted-syntax` configurations based on extracted flags and templates.
- Aggregates configurations and determines the overall severity (`warn` or `error`).
- Outputs the final configuration to `eslint.config.mjs` in the parent directory.

## Examples
**Input Rule**: "No default parameters in functions"  
**Generated Output**:  
```json
{
  "rule": { "no-restricted-syntax": ["error", {"selector": "AssignmentPattern", "message": "No default parameters allowed!"}] },
  "violation": "function foo(x = 0) {}",
  "expected_error": "No default parameters allowed!",
  "explanation": "This rule prevents default parameters to avoid silent fallbacks."
}
```

**Input Rule**: "Avoid using Math.random()"  
**Generated Output**:  
```json
{
  "rule": { "no-restricted-globals": ["error", {"name": "Math.random", "message": "Use a seeded PRNG instead!"}] },
  "violation": "const rand = Math.random();",
  "expected_error": "Use a seeded PRNG instead!",
  "explanation": "Math.random() is non-deterministic; use a seeded PRNG for reproducibility."
}
```

## Notes
- The script generates an ESLint Flat Config file (`eslint.config.mjs`) in your project root. Ensure your IDE/editor's ESLint integration supports this format and is configured to find it.
- The included `violation.js` is just for demonstrating rules within the `rules2lint` directory itself; the primary purpose is to generate a config for your main project files located outside `rules2lint`.

## Troubleshooting

### Script Errors
- **`ModuleNotFoundError: No module named 'config'` (or similar)**: Ensure you are running the command `python main.py` from the `rules2lint/` directory where all the `.py` files reside.
- **`npm ERR! EPERM: operation not permitted, mkdir 'C:\'` (or similar on Windows)**: This usually indicates an npm configuration issue trying to install globally or in the wrong place. Common fixes:
    - Run `npm config set prefix ""` in your terminal and try the `npm install` command again.
    - Ensure you are running the command from *within* the `rules2lint` directory.
    - If issues persist, research resetting npm permissions or configuration on Windows.
- **OpenAI API Errors**: Check your `.env` file for the correct `OPENAI_API_KEY`. Ensure you have API credits and the API is reachable.
- **Other Python Errors**: Check the traceback for specific issues within the Python modules (`main.py`, `llm_interactions.py`, etc.).

### Linting Not Working in Editor (Cursor/VS Code)
If `eslint.config.mjs` is generated successfully but you don't see linting errors in your JavaScript files:
1.  **Enable Flat Config (CRUCIAL!)**: Go to Settings (`Ctrl+,` or `Cmd+,`), search for `eslint.useFlatConfig`, and **ensure the checkbox is CHECKED**. This tells the ESLint extension to look for `eslint.config.mjs`.
2.  **Check ESLint Output Panel**: Go to `View -> Output`, and select "ESLint" from the dropdown. Look for errors related to loading the config file or other issues. If flat config was disabled, you might see messages indicating it ignored `eslint.config.mjs`.
3.  **Restart ESLint Server**: After enabling flat config or if the output panel shows errors, use the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`), type `ESLint: Restart ESLint Server`, and run the command.
4.  **Restart Editor**: As a last resort, close and reopen Cursor/VS Code.
5.  **Check for Conflicts**: Make sure you don't have older ESLint config files (like `.eslintrc.json`, `.eslintrc.js`) in your project root that might conflict.

For more on structured outputs, see the [OpenAI Structured Outputs Guide](https://platform.openai.com/docs/guides/structured-outputs).
For more on ESLint Flat Config, see the [ESLint Configuration Files Guide](https://eslint.org/docs/latest/use/configure/configuration-files).
- **ESLint config not applied:** Ensure the generated `eslint.config.mjs` is in the correct project root directory (parent of `rules2lint`) and that your editor's ESLint extension is configured to find/use it (check extension settings, restart server/editor).

## License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details. 
