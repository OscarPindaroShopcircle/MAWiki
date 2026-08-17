# JinjaX Go to Definition

Ctrl/Cmd-click (or F12) on a component tag like `common.Button` in a `.jinja`
file jumps to `src/frontend/components/common/Button.jinja`.

It's a regex-based `DefinitionProvider`, not a real parser: it matches any
dotted identifier whose last segment is PascalCase, maps segments to
subfolders under `jinjaxGoto.componentsDir` (default
`src/frontend/components`, configurable in settings), and jumps there if the
file exists. It doesn't understand `{% def %}` params, macros, or catch typos
— it's just "jump to the file".

## Install (no build step, plain JS)

1. In VS Code (including a Remote-WSL window), open the Command Palette.
2. Run **Developer: Install Extension from Location...**
3. Select this folder: `tools/vscode-jinjax-goto`.
4. Reload the window if prompted.

To uninstall, find "JinjaX Go to Definition" in the Extensions view and
uninstall it normally.
