# Agentic Engineering

Notes on building, testing, and shipping agent systems, published at [andriykislitsyn.github.io/agentic-engineering](https://andriykislitsyn.github.io/agentic-engineering/).

Articles come with code you can run. Tests for skills, MCP servers, and RAG pipelines live next to the article that explains them, and CI validates the plugins.

```
site/       Astro site deployed to GitHub Pages
  src/content/articles/   One markdown file per article
plugins/    Claude Code plugins, each with an eval suite in evals/
```

## Install the plugins

```bash
claude plugin marketplace add andriykislitsyn/agentic-engineering
claude plugin install permission-rules@agentic-engineering
claude plugin install guard-hooks@agentic-engineering
claude plugin install macuitest@agentic-engineering
```

## Run the hook tests

`guard-hooks` has no skill to eval. Its tests are plain `unittest` and cost nothing. CI runs them on every PR that touches the plugin.

```bash
python3 -m unittest discover -s plugins/guard-hooks/tests -v
```

## Run a plugin's evals

Run them locally before a PR that touches `plugins/`. CI runs only `claude plugin validate` on PRs, and runs the evals on demand through the `Skill evals` workflow, which needs an `ANTHROPIC_API_KEY` repository secret. Locally:

```bash
claude plugin eval plugins/permission-rules --ablation none --model claude-sonnet-5 --no-publish
```

`--ablation none` scores whether the skill fires when it should and stays quiet when it shouldn't. Drop it to add a no-plugin baseline and see how much the skill actually helps.

## Run the site locally

```bash
npm ci --prefix site
npm run --prefix site dev
```

Pushing to `main` deploys the site through `.github/workflows/pages.yml`.

## License

Articles in `site/src/content/` are under [CC BY 4.0](site/src/content/LICENSE): reuse them with attribution. Code is under [Apache 2.0](LICENSE).
