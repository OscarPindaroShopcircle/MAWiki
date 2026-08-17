const vscode = require("vscode");
const path = require("path");
const fs = require("fs");

// JinjaX resolves a tag like <common.Button> against the catalog root by
// treating every segment but the last as a subfolder and the last as the
// PascalCase file name: components_dir/common/Button.jinja. This holds no
// matter which file does the referencing, so no relative-path handling
// is needed.
function resolveComponentPath(document, word) {
  const segments = word.split(".");
  if (segments.length < 2) return null;

  const last = segments[segments.length - 1];
  if (!/^[A-Z]/.test(last)) return null;

  const workspaceFolder =
    vscode.workspace.getWorkspaceFolder(document.uri) ||
    vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return null;

  const config = vscode.workspace.getConfiguration("jinjaxGoto", document.uri);
  const componentsDir = config.get("componentsDir", "src/frontend/components");

  const base = path.join(workspaceFolder.uri.fsPath, componentsDir);
  const filePath = path.join(base, ...segments.slice(0, -1), `${last}.jinja`);

  return fs.existsSync(filePath) ? filePath : null;
}

class JinjaxDefinitionProvider {
  provideDefinition(document, position) {
    const range = document.getWordRangeAtPosition(position, /[A-Za-z_][A-Za-z0-9_.]*/);
    if (!range) return undefined;

    const filePath = resolveComponentPath(document, document.getText(range));
    if (!filePath) return undefined;

    // Without an explicit originSelectionRange, VS Code underlines/selects
    // using the language's default word pattern instead of ours, splitting
    // the link at the dot. Setting it here makes the whole "common.Icon"
    // clickable as one unit.
    const targetRange = new vscode.Range(0, 0, 0, 0);
    return [
      {
        originSelectionRange: range,
        targetUri: vscode.Uri.file(filePath),
        targetRange,
        targetSelectionRange: targetRange,
      },
    ];
  }
}

function activate(context) {
  const selector = { pattern: "**/*.jinja" };
  context.subscriptions.push(
    vscode.languages.registerDefinitionProvider(selector, new JinjaxDefinitionProvider())
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
