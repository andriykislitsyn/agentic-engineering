import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://andriykislitsyn.github.io',
  base: '/agentic-engineering',
  markdown: {
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
    },
  },
});
