import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, mergeConfig } from 'vite'
import baseConfig from './vite.config'

const here = path.dirname(fileURLToPath(import.meta.url))

export default mergeConfig(
  baseConfig,
  defineConfig({
    mode: 'e2e',
    resolve: {
      alias: [
        {
          find: /^\.\.\/services$/,
          replacement: path.resolve(here, 'e2e/httpPlaceService.e2e.ts'),
        },
      ],
    },
    server: {
      proxy: {
        '/api/v1': {
          target: process.env.PAWLOCAL_API_PROXY_TARGET ?? 'http://127.0.0.1:18001',
          changeOrigin: true,
        },
      },
    },
  }),
)
