# 🧠 Antigravity Workspace Memory: AI Test Case Generator

This document serves as permanent project memory and context for any Antigravity AI assistant opening this workspace.

---

## 📌 Project Overview
- **Project Name:** AI Test Case Generator (`ai-testgen`)
- **Version:** `0.5.0`
- **Owner / Author:** Rajesh Kumar
- **Distribution Package:** `ai-testgen-0.5.0.vsix` (root directory)
- **Primary Technologies:** 
  - **VS Code Extension:** TypeScript, VS Code Extension API, CodeLens Providers, SecretStorage
  - **Core Engines:** Python 3 (standard library only: `ast`, `re`, `json`, `subprocess`, `urllib`)
  - **Supported Target Languages:** **Python (pytest)** and **Salesforce Apex**
  - **Supported LLM Providers:** Google Gemini (`gemini-2.5-flash`), OpenAI (`gpt-4o`, `gpt-4o-mini`), Groq, Ollama, or any OpenAI-compatible API.

---

## 📜 Full Conversation & Development History

### Phase 1: Python Pytest Generator & Extension (v0.1.0 – v0.4.0)
1. **Initial Requirement:** User wanted an AI-powered test case generator that creates comprehensive pytest test cases for Python functions.
2. **Key Capabilities Implemented:**
   - **AST Analysis (`engine/analyzer.py`):** Parses Python code with native AST, extracts functions, arguments, docstrings, return types, local imports, and workspace fixtures.
   - **Cross-File Dependency Awareness:** Automatically follows local imports and injects imported class definitions into the prompt.
   - **Prompt Engineering (`engine/generator.py`):** Generates happy paths, edge cases, boundaries, negative tests, and parametrized cases.
   - **Dual API Key Fallback:** Failover system between primary and secondary API keys for quota/rate limit resilience.
   - **AST Validation & Self-Healing (`engine/validator.py`):** Validates generated Python syntax via AST before saving. Re-prompts AI if syntax is invalid.
   - **Pytest Runner:** Executes pytest directly and parses test outcomes into structured JSON.
   - **Recursive Project Scanner (`engine/scanner.py`):** Recursively scans entire codebases, detects untested functions, and batch generates tests.
   - **VS Code Extension (`src/extension.ts`):** Registers CodeLens "🧪 Generate Tests" above `def` lines, context menu actions, and commands.

### Phase 2: Deployment & Sharing Question
- **User Question:** *"is our project is ready for deployement ? can we deploy it on the vd code oiur shold i test it ? suppose i want to use my extension to some other person for teating how can they use my extension"*
- **Resolution:**
  - Packaged the extension into `ai-testgen-0.5.0.vsix` via `@vscode/vsce`.
  - Documented exact file sharing steps: share `ai-testgen-0.5.0.vsix` with other users.
  - Users install via VS Code: **Extensions (`Ctrl+Shift+X`) ➔ `...` ➔ Install from VSIX...** or `code --install-extension ai-testgen-0.5.0.vsix`.

### Phase 3: Scope Expansion — Salesforce Apex (v0.5.0)
- **User Request:** *"can we increase the scope like can we also include the salesforce in teh salesforce also can we geenrate the test cases in the salesfroce what do u think on this? along woith oythin it should suppoet the salesforce also it should be at enterprises level and production ready"*
- **Architecture Built:**
  1. **`engine/apex_analyzer.py`**: Regex-based Apex parser. Extracts classes, methods, annotations (`@AuraEnabled`, `@RestResource`, `@future`, `@InvocableMethod`), SOQL queries, DML operations, and SObject references. Filters out control statements (`if`, `for`, `while`, `catch`).
  2. **`engine/apex_generator.py`**: Enterprise Apex test generator. Enforces bulk testing (200+ records), resets governor limits with `Test.startTest()` / `Test.stopTest()`, mocks HTTP callouts (`HttpCalloutMock`), and handles async Apex (`@future`, `Queueable`, `Database.Batchable`).
  3. **`engine/apex_validator.py`**: Checks brace/bracket/parentheses balancing, enforces `@isTest` and assertions, and flags anti-patterns like `SeeAllData=true`.
  4. **`engine/apex_main.py`**: CLI orchestrator for Salesforce Apex test generation.
  5. **`src/extension.ts`**: Adds Apex CodeLens "🧪 Generate Apex Tests" and commands for `.cls` files.
  6. **`examples/AccountService.cls`**: Production-grade sample Apex class.
  7. **Unit Tests:** Added 28 new tests in `tests/test_apex_*.py`, bringing total passing tests to 150.

### Phase 4: Feature Testing & Demo Project
- **User Request:** *"see in our system i want to test everthing like all the features of oiur system then only i can explain it to otyhers right"*
- **User Follow-up:** *"I want to test the things like from the programming and like we will built one projec tin that can we test ?"*
- **Action Taken:**
  - Built a complete demo enterprise system inside [`demo_app/`](file:///c:/Users/rajeshkumar/Desktop/Ai%20Test%20Case%20Generator/demo_app):
    - `demo_app/models.py`: Domain dataclasses (`User`, `Product`, `OrderItem`, `Order`).
    - `demo_app/payment_service.py`: Business logic importing `models.py` to test cross-file dependency resolution.
    - `demo_app/auth_service.py`: Password validation and authentication.
    - `demo_app/CaseManager.cls`: Salesforce Apex support case manager.
    - `demo_app/test_all_features.py`: Programmatic verification suite running all 8 system features.
  - Re-packaged `ai-testgen-0.5.0.vsix` with the updated code.

---

## 🗂️ Workspace Architecture Map

```text
Ai Test Case Generator/
├── ai-testgen-0.5.0.vsix        # 📦 Distribution package to share with users
├── AGENTS.md                    # 🧠 Persistent AI workspace memory
├── GEMINI.md                    # 🧠 Persistent AI workspace memory
├── CONVERSATION_HISTORY.md      # 💬 Detailed log of past interactions & decisions
├── package.json                 # Extension manifest (v0.5.0)
├── README.md                    # Full user & enterprise documentation
├── run.py                       # Quick CLI runner
│
├── demo_app/                    # 🏢 Realistic Enterprise Test Bed
│   ├── models.py                # Dataclass models (cross-file resolution)
│   ├── payment_service.py       # E-commerce payment & tax calculations
│   ├── auth_service.py          # Security & auth logic
│   ├── CaseManager.cls          # Salesforce Apex class (SOQL, DML, AuraEnabled)
│   ├── test_all_features.py     # 🚀 Master verification script (runs all 8 features)
│   └── generated_tests/         # Auto-generated tests for demo_app
│
├── engine/                      # ⚙️ Core Generation & Analysis Engines
│   ├── analyzer.py              # Python AST parser & dependency resolver
│   ├── apex_analyzer.py         # Salesforce Apex regex parser & pattern detector
│   ├── generator.py             # Python AI prompt generator & API caller
│   ├── apex_generator.py        # Apex AI prompt generator & governor rules
│   ├── validator.py             # Python AST syntax validator & pytest runner
│   ├── apex_validator.py        # Apex syntax, brace & best practices validator
│   ├── scanner.py               # Workspace-wide recursive batch scanner
│   ├── main.py                  # Python CLI orchestrator
│   └── apex_main.py             # Apex CLI orchestrator
│
├── src/                         # 💻 VS Code Extension (TypeScript)
│   └── extension.ts             # CodeLens for .py & .cls, SecretStorage, commands
│
├── tests/                       # 🧪 Automated Test Suite (150 tests passing)
│   ├── test_analyzer.py
│   ├── test_apex_analyzer.py
│   ├── test_apex_generator.py
│   ├── test_apex_main.py
│   ├── test_apex_validator.py
│   ├── test_generator.py
│   ├── test_main.py
│   ├── test_scanner.py
│   └── test_validator.py
│
└── examples/                    # 📁 Reference examples
    ├── sample.py                # Python sample
    ├── AccountService.cls       # Apex sample
    └── generated_tests/         # Generated test files
```

---

## 🛠️ Key Commands Cheat Sheet

| Action | Command |
|---|---|
| Run all 150 automated unit tests | `python -m pytest tests/` |
| Run all 8 system features on demo app | `python demo_app/test_all_features.py` |
| Scan workspace for untested Python functions | `python engine/scanner.py demo_app --dry-run` |
| Compile TypeScript extension | `npm run compile` (or `cmd /c "npm run compile"`) |
| Package into `.vsix` installer | `cmd /c "npx @vscode/vsce package"` |
| Install extension in VS Code | `code --install-extension ai-testgen-0.5.0.vsix` |
| Launch VS Code Extension Dev Host | Press `F5` in VS Code |

---

## 🔒 Security & Credential Rules
- API keys are **never** committed to version control.
- In VS Code, keys are stored in `ctx.secrets` (`SecretStorage`).
- For CLI usage, keys are passed via `$env:TESTGEN_API_KEY` or `--api-key`.
