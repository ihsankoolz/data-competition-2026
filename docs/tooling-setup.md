# Tooling setup (Windows, ~40 minutes)

Run from the repo root in **Git Bash** (Claude Code on Windows uses Git Bash).

## 1. Accounts and keys (5 min)

- Context7 free key: https://context7.com/dashboard → set a **user** environment variable `CONTEXT7_API_KEY` (Windows: System Properties → Environment Variables), then restart your terminal.
- Anthropic API key (for `LLM_MODE=record` later): put it in `.env` (never commit).

## 2. Global CLIs (5 min)

```bash
npm i -g typescript typescript-language-server pyright @mermaid-js/mermaid-cli
```

## 3. Claude Code plugins (5 min) — inside Claude Code

```
/plugin install frontend-design@claude-plugins-official
/plugin install typescript-lsp@claude-plugins-official
/plugin install pyright-lsp@claude-plugins-official
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install commit-commands@claude-plugins-official
```

- If a name isn't found, run `/plugin marketplace add anthropics/claude-plugins-official` first.

## 4. MCP servers (5 min)

- Already defined in `.mcp.json` (project scope). Start Claude Code in the repo; approve the four servers when prompted.
- Check with `/mcp`. All four should say "connected".
- First Playwright use downloads Chromium (~2 min). If it fails: `npx playwright install chromium`.
- If a stdio server won't start on Windows, the `cmd /c npx` wrapper in `.mcp.json` is usually the fix (already applied).

## 5. Hooks (2 min)

- Already defined in `.claude/settings.json` with Python scripts in `.claude/hooks/`.
- Check with `/hooks`. Test: ask Claude to edit `.env` → it should be blocked.
- Formatting starts working once `ruff` (Python) and `prettier` (web) are installed by the scaffold.

## 6. Installed by the agents during the build (not now)

- Python: added with `uv add` during scaffold (see D-013).
- Web: `npx shadcn@latest init -b radix`, then shadcn components, `@magicui/*`, `motion`, `@number-flow/react`, `echarts`, `echarts-for-react`, `sonner`, `react-diff-viewer-continued`.

## 7. Later in the week

- **Sat morning:** pick a palette at https://tweakcn.com and paste the CSS variables into `apps/web/app/globals.css`.
- **Mon evening:** `/plugin install security-guidance@claude-plugins-official` for a final security pass; `npx skills add vercel-labs/agent-skills` for the web-design-guidelines review.
- **Tue:** install Cap (https://cap.so) for the video. Install D2 (https://d2lang.com) for the architecture diagram, or use Mermaid.
