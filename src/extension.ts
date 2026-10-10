/**
 * AI Test Case Generator – VS Code Extension (v0.5.0)
 *
 * Supports BOTH Python and Salesforce Apex:
 *
 * Registers commands:
 *   1. testgen.generateForFunction  – generate tests for the function/method under cursor
 *   2. testgen.generateForFile      – generate tests for every function/method in the file
 *   3. testgen.generateForProject   – scan entire project and generate missing tests
 *   4. testgen.runTests             – run pytest on generated test files (Python)
 *   5. testgen.setApiKey            – securely store the primary API key
 *   6. testgen.setFallbackKey       – securely store a fallback API key
 *   7. testgen.initConfig           – create a .testgenrc.json config file
 *   8. testgen.generateApexTests    – generate Apex test classes for .cls files
 *   9. testgen.generateApexForMethod – generate Apex tests for the method under cursor
 *
 * Also provides CodeLensProviders that show  "🧪 Generate Tests"
 * above every  def  in Python files and every method in Apex .cls files.
 */

import * as vscode from "vscode";
import { spawn, ChildProcess } from "child_process";
import * as path from "path";
import * as fs from "fs";

// ── Activation ───────────────────────────────────────────────────

export function activate(ctx: vscode.ExtensionContext) {
  // ── Python Commands ────────────────────────────────────────
  ctx.subscriptions.push(
    vscode.commands.registerCommand("testgen.generateForFunction", () =>
      handleGenerate(ctx, "function")
    ),
    vscode.commands.registerCommand("testgen.generateForFile", () =>
      handleGenerate(ctx, "file")
    ),
    vscode.commands.registerCommand("testgen.generateForProject", () =>
      handleGenerateProject(ctx)
    ),
    vscode.commands.registerCommand("testgen.runTests", () =>
      handleRunTests()
    ),
    vscode.commands.registerCommand("testgen.setApiKey", () =>
      setApiKey(ctx, "primary")
    ),
    vscode.commands.registerCommand("testgen.setFallbackKey", () =>
      setApiKey(ctx, "fallback")
    ),
    vscode.commands.registerCommand("testgen.initConfig", () =>
      handleInitConfig()
    )
  );

  // ── Salesforce Apex Commands ───────────────────────────────
  ctx.subscriptions.push(
    vscode.commands.registerCommand("testgen.generateApexTests", () =>
      handleApexGenerate(ctx, "file")
    ),
    vscode.commands.registerCommand("testgen.generateApexForMethod", () =>
      handleApexGenerate(ctx, "method")
    )
  );

  // ── Python CodeLens ────────────────────────────────────────
  const pythonCodeLens = new TestGenCodeLensProvider();
  ctx.subscriptions.push(
    vscode.languages.registerCodeLensProvider(
      { language: "python", scheme: "file" },
      pythonCodeLens
    )
  );

  // ── Apex CodeLens ──────────────────────────────────────────
  const apexCodeLens = new ApexCodeLensProvider();
  ctx.subscriptions.push(
    vscode.languages.registerCodeLensProvider(
      { language: "apex", scheme: "file" },
      apexCodeLens
    )
  );

  // Also register for plain-text .cls files (when Apex extension is not installed)
  const clsFilter: vscode.DocumentFilter = {
    scheme: "file",
    pattern: "**/*.cls",
  };
  ctx.subscriptions.push(
    vscode.languages.registerCodeLensProvider(clsFilter, apexCodeLens)
  );

  console.log("AI Test Case Generator activated (Python + Salesforce Apex)");
}

export function deactivate() {}

// ── API Key management ───────────────────────────────────────────

async function setApiKey(
  ctx: vscode.ExtensionContext,
  kind: "primary" | "fallback" = "primary"
): Promise<void> {
  const label = kind === "primary" ? "Primary" : "Fallback";
  const secretKey =
    kind === "primary" ? "testgen.apiKey" : "testgen.fallbackKey";

  const key = await vscode.window.showInputBox({
    prompt: `Enter your ${label} AI API key (Gemini, OpenAI, etc.)`,
    password: true,
    placeHolder: "AIza...",
    ignoreFocusOut: true,
  });

  if (key) {
    await ctx.secrets.store(secretKey, key);
    vscode.window.showInformationMessage(
      `✅ ${label} API key saved securely.`
    );
  }
}

/**
 * Retrieve the primary key (required) and optional fallback key.
 * Returns { primary, fallback } or undefined if no key at all.
 */
async function getApiKeys(
  ctx: vscode.ExtensionContext
): Promise<{ primary: string; fallback?: string } | undefined> {
  // ── Primary key ────────────────────────────────────────────
  let primary = await ctx.secrets.get("testgen.apiKey");
  if (!primary) { primary = process.env.TESTGEN_API_KEY; }

  if (!primary) {
    const action = await vscode.window.showWarningMessage(
      "No API key configured for AI Test Case Generator.",
      "Set API Key",
      "Cancel"
    );
    if (action === "Set API Key") {
      await setApiKey(ctx, "primary");
      primary = await ctx.secrets.get("testgen.apiKey");
    }
  }
  if (!primary) { return undefined; }

  // ── Fallback key (optional) ────────────────────────────────
  let fallback = await ctx.secrets.get("testgen.fallbackKey");
  if (!fallback) { fallback = process.env.TESTGEN_FALLBACK_KEY; }

  return { primary, fallback: fallback || undefined };
}

// ── Python path resolution ───────────────────────────────────────

function getPythonPath(): string {
  const cfg = vscode.workspace.getConfiguration("testgen");
  const configured = cfg.get<string>("pythonPath", "python");

  // Try to read from the official Python extension
  if (configured === "python") {
    const pythonCfg = vscode.workspace.getConfiguration("python");
    const interpreterPath = pythonCfg.get<string>("defaultInterpreterPath");
    if (interpreterPath) { return interpreterPath; }
  }

  return configured;
}

// ── Function name under cursor ───────────────────────────────────

function getFunctionAtCursor(
  document: vscode.TextDocument,
  position: vscode.Position
): string | undefined {
  // Walk backwards from cursor to find the nearest  def  line
  for (let line = position.line; line >= 0; line--) {
    const text = document.lineAt(line).text;
    const match = text.match(/^\s*(?:async\s+)?def\s+(\w+)\s*\(/);
    if (match) {
      return match[1];
    }
  }
  return undefined;
}

// ── Apex method name under cursor ────────────────────────────────

function getApexMethodAtCursor(
  document: vscode.TextDocument,
  position: vscode.Position
): string | undefined {
  // Walk backwards to find the nearest Apex method declaration
  for (let line = position.line; line >= 0; line--) {
    const text = document.lineAt(line).text;
    // Match: public/private/global [static] [virtual] ReturnType methodName(
    const match = text.match(
      /^\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public|private|global|protected)?\s*(?:(?:static|virtual|abstract|override|testMethod)\s+)*[\w<>,\s\[\]]+?\s+(\w+)\s*\(/
    );
    if (match) {
      const name = match[1];
      // Skip class/interface/enum declarations
      if (
        !text.match(/\b(class|interface|enum|trigger)\b/i) &&
        name !== "if" && name !== "for" && name !== "while" &&
        name !== "switch" && name !== "catch" && name !== "new"
      ) {
        return name;
      }
    }
  }
  return undefined;
}

// ── Core: call the Python engine ─────────────────────────────────

async function handleGenerate(
  ctx: vscode.ExtensionContext,
  scope: "function" | "file"
): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "python") {
    vscode.window.showWarningMessage("Open a Python file first.");
    return;
  }

  // Save unsaved changes so the engine sees the latest code
  await editor.document.save();

  // Resolve API keys (primary + optional fallback)
  const keys = await getApiKeys(ctx);
  if (!keys) { return; }

  const cfg = vscode.workspace.getConfiguration("testgen");
  const filePath = editor.document.fileName;
  const engineScript = path.join(ctx.extensionPath, "engine", "main.py");
  const outputFolder = cfg.get<string>("outputFolder", "generated_tests");
  const baseUrl = cfg.get<string>(
    "apiBaseUrl",
    "https://generativelanguage.googleapis.com/v1beta/openai"
  );
  const model = cfg.get<string>("model", "gemini-2.5-flash");
  const pythonPath = getPythonPath();

  // Build CLI args
  const args: string[] = [
    engineScript,
    "--file", filePath,
    "--output", outputFolder,
    "--api-key", keys.primary,
    "--base-url", baseUrl,
    "--model", model,
    "--json",
  ];

  // Add fallback key if configured
  if (keys.fallback) {
    args.push("--fallback-key", keys.fallback);
  }

  // Add validation flag
  const validateTests = cfg.get<boolean>("validateTests", true);
  if (!validateTests) {
    args.push("--no-validate");
  }

  // If scoped to a single function, find it
  if (scope === "function") {
    const funcName =
      getFunctionAtCursor(editor.document, editor.selection.active);
    if (!funcName) {
      vscode.window.showWarningMessage(
        "Place your cursor inside a Python function to generate tests for it."
      );
      return;
    }
    args.push("--function", funcName);
  }

  // Run with progress
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "🧪 AI Test Case Generator",
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: "Generating test cases…" });

      try {
        const result = await runPythonEngine(pythonPath, args);
        const parsed = JSON.parse(result);

        if (parsed.error) {
          vscode.window.showErrorMessage(`TestGen: ${parsed.error}`);
          return;
        }

        // Show summary
        const testResults = parsed.results?.filter((r: any) => r.test_results);
        let msg = `✅ Generated tests for ${parsed.success}/${parsed.total} function(s)`;

        if (testResults?.length > 0) {
          const totalPassed = testResults.reduce((s: number, r: any) => s + (r.test_results?.passed || 0), 0);
          const totalFailed = testResults.reduce((s: number, r: any) => s + (r.test_results?.failed || 0), 0);
          msg += ` | pytest: ${totalPassed} passed, ${totalFailed} failed`;
        }

        const openAction = "Open Tests";
        const choice = await vscode.window.showInformationMessage(
          msg,
          openAction
        );

        // Open the first generated file
        if (choice === openAction && parsed.results?.length) {
          const firstOk = parsed.results.find(
            (r: any) => r.status === "ok" && r.file
          );
          if (firstOk) {
            const doc = await vscode.workspace.openTextDocument(firstOk.file);
            await vscode.window.showTextDocument(doc, { preview: false });
          }
        }

        // Report errors for failed functions
        for (const r of parsed.results || []) {
          if (r.status === "error") {
            vscode.window.showWarningMessage(
              `⚠ ${r.function}: ${r.error}`
            );
          }
        }

        // Auto-run tests if configured
        const autoRun = cfg.get<boolean>("autoRunTests", false);
        if (autoRun && parsed.success > 0) {
          await runGeneratedTests(pythonPath, parsed.output_dir);
        }
      } catch (err: any) {
        vscode.window.showErrorMessage(
          `TestGen failed: ${err.message || err}`
        );
      }
    }
  );
}

function runPythonEngine(
  python: string,
  args: string[],
  token?: vscode.CancellationToken
): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn(python, args, {
      env: { ...process.env },
      cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));

    // Support cancellation
    if (token) {
      token.onCancellationRequested(() => {
        proc.kill("SIGTERM");
        reject(new Error("Cancelled by user"));
      });
    }

    proc.on("error", (err) => {
      reject(
        new Error(
          `Could not start Python ("${python}").\n` +
            `Make sure Python is installed and the path is correct.\n` +
            `Details: ${err.message}`
        )
      );
    });

    proc.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(
          new Error(stderr || `Python process exited with code ${code}`)
        );
      }
    });
  });
}

// ── Python CodeLens Provider ─────────────────────────────────────

class TestGenCodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  public readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  provideCodeLenses(
    document: vscode.TextDocument
  ): vscode.CodeLens[] {
    const lenses: vscode.CodeLens[] = [];

    for (let i = 0; i < document.lineCount; i++) {
      const line = document.lineAt(i);
      const match = line.text.match(/^\s*(?:async\s+)?def\s+(\w+)\s*\(/);

      if (match && !match[1].startsWith("_")) {
        const range = new vscode.Range(i, 0, i, line.text.length);
        lenses.push(
          new vscode.CodeLens(range, {
            title: "🧪 Generate Tests",
            command: "testgen.generateForFunction",
            tooltip: `Generate pytest tests for ${match[1]}()`,
          })
        );
      }
    }

    return lenses;
  }
}

// ── Apex CodeLens Provider ───────────────────────────────────────

class ApexCodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  public readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  provideCodeLenses(
    document: vscode.TextDocument
  ): vscode.CodeLens[] {
    const lenses: vscode.CodeLens[] = [];
    const fileName = document.fileName.toLowerCase();

    // Only apply to .cls and .trigger files
    if (!fileName.endsWith(".cls") && !fileName.endsWith(".trigger")) {
      return lenses;
    }

    // Skip if this is already a test class
    const fullText = document.getText();
    if (fullText.includes("@isTest") || fullText.includes("@IsTest")) {
      return lenses;
    }

    // Add a "Generate All Tests" lens at the class declaration
    for (let i = 0; i < document.lineCount; i++) {
      const line = document.lineAt(i);
      const classMatch = line.text.match(
        /\b(?:public|private|global)\s+(?:(?:virtual|abstract|with\s+sharing|without\s+sharing|inherited\s+sharing)\s+)*class\s+(\w+)/i
      );
      if (classMatch) {
        const range = new vscode.Range(i, 0, i, line.text.length);
        lenses.push(
          new vscode.CodeLens(range, {
            title: "🧪 Generate All Apex Tests",
            command: "testgen.generateApexTests",
            tooltip: `Generate Apex test class for ${classMatch[1]}`,
          })
        );
        break;
      }
    }

    // Add per-method lenses
    for (let i = 0; i < document.lineCount; i++) {
      const line = document.lineAt(i);
      const methodMatch = line.text.match(
        /^\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public|private|global|protected)\s+(?:(?:static|virtual|abstract|override)\s+)*[\w<>,\s\[\]]+?\s+(\w+)\s*\(/
      );

      if (methodMatch) {
        const name = methodMatch[1];
        // Skip class/interface declarations and common non-method keywords
        if (
          !line.text.match(/\b(class|interface|enum|trigger)\b/i) &&
          name !== "if" && name !== "for" && name !== "while" &&
          name !== "switch" && name !== "catch" && name !== "new"
        ) {
          const range = new vscode.Range(i, 0, i, line.text.length);
          lenses.push(
            new vscode.CodeLens(range, {
              title: "🧪 Generate Tests",
              command: "testgen.generateApexForMethod",
              tooltip: `Generate Apex tests for ${name}()`,
            })
          );
        }
      }
    }

    return lenses;
  }
}

// ── Generate for Entire Project (with cancellation) ──────────────

async function handleGenerateProject(
  ctx: vscode.ExtensionContext
): Promise<void> {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showWarningMessage("Open a workspace folder first.");
    return;
  }

  const keys = await getApiKeys(ctx);
  if (!keys) { return; }

  const cfg = vscode.workspace.getConfiguration("testgen");
  const pythonPath = getPythonPath();
  const scannerScript = path.join(ctx.extensionPath, "engine", "scanner.py");
  const allKeys = keys.fallback ? `${keys.primary},${keys.fallback}` : keys.primary;
  const baseUrl = cfg.get<string>(
    "apiBaseUrl",
    "https://generativelanguage.googleapis.com/v1beta/openai"
  );
  const model = cfg.get<string>("model", "gemini-2.5-flash");

  const args: string[] = [
    scannerScript,
    "--project", workspaceFolder.uri.fsPath,
    "--api-key", allKeys,
    "--base-url", baseUrl,
    "--model", model,
    "--json",
  ];

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "🧪 AI Test Case Generator — Project Scan",
      cancellable: true,
    },
    async (progress, token) => {
      progress.report({ message: "Scanning project for untested functions…" });

      try {
        const result = await runPythonEngine(pythonPath, args, token);
        const parsed = JSON.parse(result);

        const msg =
          `📊 Project scan complete: ` +
          `${parsed.tests_generated} tests generated, ` +
          `${parsed.functions_skipped} skipped, ` +
          `${parsed.tests_failed} errors`;

        vscode.window.showInformationMessage(msg);
      } catch (err: any) {
        if (err.message === "Cancelled by user") {
          vscode.window.showInformationMessage("Project scan cancelled.");
        } else {
          vscode.window.showErrorMessage(
            `Project scan failed: ${err.message || err}`
          );
        }
      }
    }
  );
}

// ── Run Generated Tests ──────────────────────────────────────────

async function handleRunTests(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showWarningMessage("Open a workspace folder first.");
    return;
  }

  const pythonPath = getPythonPath();
  const cfg = vscode.workspace.getConfiguration("testgen");
  const outputFolder = cfg.get<string>("outputFolder", "generated_tests");

  // Determine which test directory to run
  let testDir: string;
  if (editor && editor.document.languageId === "python") {
    // If a Python file is open, look for its sibling generated_tests/
    const sourceDir = path.dirname(editor.document.fileName);
    const candidate = path.join(sourceDir, outputFolder);
    if (fs.existsSync(candidate)) {
      testDir = candidate;
    } else {
      // Fall back to workspace root
      testDir = path.join(workspaceFolder.uri.fsPath, outputFolder);
    }
  } else {
    testDir = path.join(workspaceFolder.uri.fsPath, outputFolder);
  }

  if (!fs.existsSync(testDir)) {
    vscode.window.showWarningMessage(
      `No generated tests found at: ${testDir}\n` +
      `Generate tests first using "TestGen: Generate Tests for Entire File".`
    );
    return;
  }

  await runGeneratedTests(pythonPath, testDir);
}

/**
 * Run pytest on a directory and show results.
 */
async function runGeneratedTests(
  pythonPath: string,
  testDir: string
): Promise<void> {
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "🧪 Running Generated Tests",
      cancellable: true,
    },
    async (progress, token) => {
      progress.report({ message: "Running pytest…" });

      const args = [
        "-m", "pytest",
        testDir,
        "-v",
        "--tb=short",
        "--no-header",
      ];

      try {
        const output = await runPythonEngine(pythonPath, args, token);
        // Parse pass/fail from output
        const passMatch = output.match(/(\d+)\s+passed/);
        const failMatch = output.match(/(\d+)\s+failed/);
        const errorMatch = output.match(/(\d+)\s+error/);

        const passed = passMatch ? parseInt(passMatch[1]) : 0;
        const failed = failMatch ? parseInt(failMatch[1]) : 0;
        const errors = errorMatch ? parseInt(errorMatch[1]) : 0;

        if (failed === 0 && errors === 0) {
          vscode.window.showInformationMessage(
            `✅ All tests passed! (${passed} passed)`
          );
        } else {
          const choice = await vscode.window.showWarningMessage(
            `⚠ Tests: ${passed} passed, ${failed} failed, ${errors} errors`,
            "Show Output"
          );
          if (choice === "Show Output") {
            const outputChannel = vscode.window.createOutputChannel("TestGen Results");
            outputChannel.clear();
            outputChannel.appendLine(output);
            outputChannel.show(true);
          }
        }
      } catch (err: any) {
        if (err.message === "Cancelled by user") {
          vscode.window.showInformationMessage("Test run cancelled.");
          return;
        }

        // pytest returns non-zero on failures — try to parse the stderr
        const errStr = err.message || "";
        const passMatch = errStr.match(/(\d+)\s+passed/);
        const failMatch = errStr.match(/(\d+)\s+failed/);
        const errorMatch = errStr.match(/(\d+)\s+error/);

        if (passMatch || failMatch || errorMatch) {
          const passed = passMatch ? parseInt(passMatch[1]) : 0;
          const failed = failMatch ? parseInt(failMatch[1]) : 0;
          const errors = errorMatch ? parseInt(errorMatch[1]) : 0;

          const choice = await vscode.window.showWarningMessage(
            `⚠ Tests: ${passed} passed, ${failed} failed, ${errors} errors`,
            "Show Output"
          );
          if (choice === "Show Output") {
            const outputChannel = vscode.window.createOutputChannel("TestGen Results");
            outputChannel.clear();
            outputChannel.appendLine(errStr);
            outputChannel.show(true);
          }
        } else {
          vscode.window.showErrorMessage(
            `Failed to run tests: ${err.message || err}`
          );
        }
      }
    }
  );
}

// ── Salesforce Apex: Generate Tests ──────────────────────────────

async function handleApexGenerate(
  ctx: vscode.ExtensionContext,
  scope: "method" | "file"
): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Open an Apex file first.");
    return;
  }

  const fileName = editor.document.fileName.toLowerCase();
  if (!fileName.endsWith(".cls") && !fileName.endsWith(".trigger")) {
    vscode.window.showWarningMessage(
      "This command works only with Apex files (.cls, .trigger)."
    );
    return;
  }

  // Save unsaved changes
  await editor.document.save();

  // Resolve API keys
  const keys = await getApiKeys(ctx);
  if (!keys) { return; }

  const cfg = vscode.workspace.getConfiguration("testgen");
  const filePath = editor.document.fileName;
  const apexEngine = path.join(ctx.extensionPath, "engine", "apex_main.py");
  const outputFolder = cfg.get<string>("outputFolder", "generated_tests");
  const baseUrl = cfg.get<string>(
    "apiBaseUrl",
    "https://generativelanguage.googleapis.com/v1beta/openai"
  );
  const model = cfg.get<string>("model", "gemini-2.5-flash");
  const pythonPath = getPythonPath();

  // Build CLI args
  const args: string[] = [
    apexEngine,
    "--file", filePath,
    "--output", outputFolder,
    "--api-key", keys.primary,
    "--base-url", baseUrl,
    "--model", model,
    "--json",
  ];

  // Add fallback key if configured
  if (keys.fallback) {
    args.push("--fallback-key", keys.fallback);
  }

  // Add validation flag
  const validateTests = cfg.get<boolean>("validateTests", true);
  if (!validateTests) {
    args.push("--no-validate");
  }

  // If scoped to a single method, find it
  if (scope === "method") {
    const methodName = getApexMethodAtCursor(
      editor.document,
      editor.selection.active
    );
    if (!methodName) {
      vscode.window.showWarningMessage(
        "Place your cursor inside an Apex method to generate tests for it."
      );
      return;
    }
    args.push("--method", methodName, "--per-method");
  }

  // Run with progress
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "🧪 AI Test Case Generator (Apex)",
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: "Generating Apex test cases…" });

      try {
        const result = await runPythonEngine(pythonPath, args);
        const parsed = JSON.parse(result);

        if (parsed.error) {
          vscode.window.showErrorMessage(`TestGen Apex: ${parsed.error}`);
          return;
        }

        let msg = `✅ Generated Apex tests: ${parsed.success}/${parsed.total} succeeded`;

        const openAction = "Open Tests";
        const choice = await vscode.window.showInformationMessage(
          msg,
          openAction
        );

        // Open the first generated file
        if (choice === openAction && parsed.results?.length) {
          const firstOk = parsed.results.find(
            (r: any) => r.status === "ok" && r.file
          );
          if (firstOk) {
            const doc = await vscode.workspace.openTextDocument(firstOk.file);
            await vscode.window.showTextDocument(doc, { preview: false });
          }
        }

        // Report errors
        for (const r of parsed.results || []) {
          if (r.status === "error") {
            vscode.window.showWarningMessage(
              `⚠ ${r.function}: ${r.error}`
            );
          }
        }
      } catch (err: any) {
        vscode.window.showErrorMessage(
          `TestGen Apex failed: ${err.message || err}`
        );
      }
    }
  );
}

// ── Initialize Config ────────────────────────────────────────────

async function handleInitConfig(): Promise<void> {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showWarningMessage("Open a workspace folder first.");
    return;
  }

  const configPath = path.join(workspaceFolder.uri.fsPath, ".testgenrc.json");

  // Check if config already exists
  try {
    await vscode.workspace.fs.stat(vscode.Uri.file(configPath));
    const overwrite = await vscode.window.showWarningMessage(
      ".testgenrc.json already exists. Overwrite?",
      "Overwrite",
      "Cancel"
    );
    if (overwrite !== "Overwrite") { return; }
  } catch {
    // File doesn't exist, proceed
  }

  const defaultConfig = {
    include: ["**/*.py", "**/*.cls", "**/*.trigger"],
    exclude: [
      "**/tests/**",
      "**/test_*.py",
      "**/*_test.py",
      "**/*Test.cls",
      "**/generated_tests/**",
      "**/node_modules/**",
      "**/__pycache__/**",
      "**/venv/**",
      "**/.venv/**",
      "**/migrations/**",
    ],
    testFramework: "pytest",
    outputDir: "generated_tests",
    model: "gemini-2.5-flash",
    maxTestsPerFunction: 15,
    skipPrivate: true,
    skipDunder: true,
    rateLimitDelay: 2,
    maxRetries: 2,
    validateBeforeSave: true,
    runAfterGenerate: false,
    style: {
      useFixtures: true,
      useParametrize: true,
      docstrings: true,
    },
    apex: {
      perMethod: false,
      bulkTestSize: 200,
      coverageTarget: 75,
    },
  };

  const content = JSON.stringify(defaultConfig, null, 2) + "\n";
  const uri = vscode.Uri.file(configPath);
  await vscode.workspace.fs.writeFile(uri, Buffer.from(content, "utf-8"));

  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(doc);

  vscode.window.showInformationMessage(
    "✅ Created .testgenrc.json — customize your project settings!"
  );
}
