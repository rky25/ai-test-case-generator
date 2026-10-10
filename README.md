# 🧪 AI Test Case Generator

Enterprise-grade AI-powered test case generator for **Python (pytest)** and **Salesforce Apex**. Designed for production systems with cross-file dependency awareness, framework intelligence, governor limits compliance, and self-healing test validation.

---

## 🌟 Key Features

### 🐍 Python (pytest) Intelligence
- **Function & File Generation**: Instant test generation via CodeLens button above `def` or editor context menu.
- **Cross-File Dependency Analysis**: Resolves local module imports and injects helper/model signatures into AI prompts.
- **Framework-Aware**: Detects FastAPI, Django, Flask, SQLAlchemy, Pydantic, Click/Typer and tailors fixtures accordingly.
- **Fixture Intelligence**: Discovers existing workspace fixtures in `conftest.py` and reuses them.
- **AST Validation & Self-Healing**: Validates syntax, imports, and assertion structures with automated re-prompting on errors.
- **Pytest Runner**: Directly executes pytest from VS Code or CLI with real-time pass/fail reporting.
- **Project-Wide Scanner**: Recursively scans entire codebases, skips already-tested functions, and batch generates tests.

### ☁️ Salesforce Apex Enterprise Engine
- **Full Apex Syntax Analysis**: Extracts classes, methods, annotations (`@AuraEnabled`, `@RestResource`, `@future`, `@InvocableMethod`), SOQL queries, and DML operations.
- **Governor Limit & Bulk Testing**: Automatically designs bulk test cases with 200+ records to ensure governor limits compliance.
- **Pattern-Specific Strategies**:
  - **SOQL / DML**: Tests 0, 1, and 200+ records, boundary checks, and `DmlException` / `QueryException`.
  - **HTTP & Web Services**: Generates `HttpCalloutMock` / `WebServiceMock` implementations.
  - **Async Apex**: Handles `@future`, `Queueable`, `Database.Batchable`, and `Schedulable` with `Test.startTest()` / `Test.stopTest()`.
  - **Triggers & Platform Events**: Covers trigger context events and `EventBus.publish()`.
  - **Security & Sharing**: Validates `with sharing`, `without sharing`, and `System.runAs()`.
- **Apex Test Validator**: Checks balanced braces, `@isTest` annotations, `Test.startTest()`/`Test.stopTest()` wrapping, assertions, and flags anti-patterns like `SeeAllData=true` or hardcoded IDs.
- **Apex CodeLens**: Shows **"🧪 Generate Apex Tests"** above Apex methods in `.cls` files.

### 🏢 Enterprise & Security Ready
- **Dual API Key Fallback**: Automatic failover from primary to fallback key if rate limits, quota exhaustion, or timeouts occur.
- **Secure Key Storage**: API keys are encrypted in VS Code's native OS credential store (`SecretStorage`).
- **Flexible Provider Support**: Works with Google Gemini (`gemini-2.5-flash`), OpenAI (`gpt-4o`, `gpt-4o-mini`), Groq, Ollama, vLLM, or any OpenAI-compatible endpoint.
- **Offline / Zero Dependency Engine**: Core Python engines use only Python standard library modules (`ast`, `re`, `json`, `urllib`).

---

## 🚀 Quick Start

### 1. Build and Compile
```bash
npm install
npm run compile
```

### 2. Configure API Keys in VS Code
Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`):
- **TestGen: Set Primary API Key** → Paste your Gemini / OpenAI API key
- *(Optional)* **TestGen: Set Fallback API Key** → Paste your backup key

### 3. Generate Tests

#### In Python (`.py` files):
- **Click CodeLens**: Click **"🧪 Generate Tests"** directly above any function or class method.
- **Right-Click**: Select **"TestGen: Generate Tests for Entire File"**.
- **Run Tests**: Run **"TestGen: Run Generated Tests"** from Command Palette.

#### In Salesforce Apex (`.cls` files):
- **Click CodeLens**: Click **"🧪 Generate Apex Tests"** above any method in a `.cls` file.
- **Right-Click**: Select **"TestGen: Generate Apex Tests for File"** or **"TestGen: Generate Apex Tests for Method"**.

---

## 📁 Output Directory Structure

Generated test files are automatically organized alongside your source code:

```
my-enterprise-project/
├── services/
│   ├── calculator.py
│   └── generated_tests/
│       ├── conftest.py                       ← Configures Python sys.path
│       └── test_calculator_add.py           ← Pytest assertions, edge cases & mocks
└── force-app/main/default/classes/
    ├── AccountService.cls
    └── generated_tests/
        └── AccountServiceTest.cls           ← @isTest class with bulk & governor tests
```

---

## ⚙️ Configuration Reference

### VS Code Settings (`settings.json`)

| Setting | Default | Description |
|---|---|---|
| `testgen.pythonPath` | `python` | Path to Python interpreter |
| `testgen.apiBaseUrl` | `https://generativelanguage.googleapis.com/v1beta/openai` | OpenAI-compatible endpoint |
| `testgen.model` | `gemini-2.5-flash` | AI model name |
| `testgen.outputFolder` | `generated_tests` | Folder name where tests are saved |
| `testgen.validateTests` | `true` | Validate test syntax & structure before saving |
| `testgen.autoRunTests` | `false` | Automatically execute pytest after generation (Python) |

### Workspace Configuration (`.testgenrc.json`)

Create `.testgenrc.json` in your workspace root (or run `TestGen: Initialize Project Config`):

```json
{
  "include": ["**/*.py", "**/*.cls"],
  "exclude": [
    "**/tests/**",
    "**/test_*.py",
    "**/*Test.cls",
    "**/generated_tests/**",
    "**/node_modules/**",
    "**/venv/**"
  ],
  "testFramework": "pytest",
  "outputDir": "generated_tests",
  "model": "gemini-2.5-flash",
  "maxTestsPerFunction": 15,
  "skipPrivate": true,
  "rateLimitDelay": 2,
  "validateBeforeSave": true,
  "runAfterGenerate": false
}
```

---

## 💻 CLI Usage (Without VS Code)

You can run both engines independently in CI/CD pipelines, headless environments, or scripts.

### 1. Python Generation (`engine/main.py`)
```bash
# Generate for entire Python file
python engine/main.py --file src/utils.py --api-key YOUR_KEY

# Generate for specific function with pytest execution
python engine/main.py --file src/utils.py --function calculate_tax --api-key YOUR_KEY --run

# Dual key fallback
python engine/main.py --file src/utils.py --api-key KEY1 --fallback-key KEY2
```

### 2. Salesforce Apex Generation (`engine/apex_main.py`)
```bash
# Generate Apex test class for entire .cls file
python engine/apex_main.py --file force-app/main/default/classes/AccountService.cls --api-key YOUR_KEY

# Generate tests for a specific Apex method
python engine/apex_main.py --file AccountService.cls --method getAccountsByIndustry --api-key YOUR_KEY

# JSON output for CI/CD integration
python engine/apex_main.py --file AccountService.cls --api-key YOUR_KEY --json
```

### 3. Project-Wide Python Scanner (`engine/scanner.py`)
```bash
# Discover untested functions across workspace
python engine/scanner.py . --dry-run

# Batch generate tests for all untested functions
python engine/scanner.py . --api-key YOUR_KEY
```

### 4. Apex Validator (`engine/apex_validator.py`)
```bash
# Validate Apex test syntax, structure, and best practices
python engine/apex_validator.py generated_tests/AccountServiceTest.cls
```

---

## 📦 Packaging & Sharing the Extension (.vsix)

To share the extension with your team or test it on another machine:

### 1. Package into a `.vsix` installer
Run:
```bash
npx @vscode/vsce package
```
This generates a file named `ai-testgen-0.5.0.vsix` in your root project folder.

### 2. Share with Team Members
Send the `ai-testgen-0.5.0.vsix` file via email, Slack, Google Drive, or your internal repository.

### 3. Install on Any Machine
In VS Code:
1. Open the Extensions view (`Ctrl+Shift+X` / `Cmd+Shift+X`).
2. Click the `...` (Views and More Actions) menu in the top-right corner of the Extensions pane.
3. Select **Install from VSIX...**
4. Pick the `ai-testgen-0.5.0.vsix` file.
5. Set your API Key using **TestGen: Set Primary API Key** from the Command Palette (`Ctrl+Shift+P`).

Alternatively via terminal:
```bash
code --install-extension ai-testgen-0.5.0.vsix
```

---

## 🧪 Running the Test Suite

Run the full automated test suite (150 tests):
```bash
python -m pytest tests/
```

Check coverage:
```bash
python -m pytest --cov=engine tests/
```

---

## 🏛️ Architecture

```
┌────────────────────────────────────────────────────────┐
│  VS Code Extension (TypeScript)                        │
│  • CodeLens for Python (defs) & Apex (.cls methods)    │
│  • Context menus & Command Palette workflows           │
│  • SecretStorage secure credential management          │
└──────────────┬─────────────────────────┬───────────────┘
               │ spawns                  │ spawns
               ▼                         ▼
┌───────────────────────────────┐ ┌────────────────────────────────┐
│  Python Engine                │ │  Salesforce Apex Engine        │
│  • analyzer.py (AST)          │ │  • apex_analyzer.py (Regex)    │
│  • generator.py (AI + Retry)  │ │  • apex_generator.py (Governor)│
│  • validator.py (AST + Pytest)│ │  • apex_validator.py (Best Pr) │
│  • scanner.py (Workspace Scan)│ │  • apex_main.py (Orchestrator) │
│  • main.py (Orchestration)    │ └────────────────┬───────────────┘
└──────────────┬────────────────┘                  │
               │                                   │ writes
               ▼                                   ▼
 ┌───────────────────────────┐       ┌───────────────────────────┐
 │ generated_tests/          │       │ generated_tests/          │
 │ ├── conftest.py           │       │ └── AccountServiceTest.cls│
 │ └── test_func.py          │       │     (200+ bulk, mocks)    │
 └───────────────────────────┘       └───────────────────────────┘
```

---

## 📄 License

MIT
