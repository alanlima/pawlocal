import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, mergeConfig } from 'vite'
import baseConfig from './vite.config'

const here = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(async (configEnv) => {
  const base = typeof baseConfig === 'function' ? await baseConfig(configEnv) : baseConfig
  return mergeConfig(base, {
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
        '/api/v1': { target: 'http://127.0.0.1:18001', changeOrigin: true },
      },
    },
  })
})
