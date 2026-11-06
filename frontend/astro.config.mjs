// @ts-check
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://quantstrategylab.github.io',
  base: '/QuantAdvisorResearch',
  output: 'static',
  build: {
    format: 'file',
  },
  trailingSlash: 'never',
  vite: {
    define: {
      __QAR_FRONTEND_ROOT__: JSON.stringify(process.cwd()),
    },
  },
});
