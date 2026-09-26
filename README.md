# Agentic Engineering

Notes on building, testing, and shipping agent systems, published at [andriykislitsyn.github.io/agentic-engineering](https://andriykislitsyn.github.io/agentic-engineering/).

Articles come with code you can run. Tests for skills, MCP servers, and RAG pipelines live next to the article that explains them, and CI runs them.

```
site/       Astro site deployed to GitHub Pages
  src/content/articles/   One markdown file per article
```

## Run the site locally

```bash
npm ci --prefix site
npm run --prefix site dev
```

Pushing to `main` deploys the site through `.github/workflows/pages.yml`.

## License

Articles in `site/src/content/` are under [CC BY 4.0](site/src/content/LICENSE): reuse them with attribution. Code is under [Apache 2.0](LICENSE).
