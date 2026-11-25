import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  plugins: [vue()],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: '../static/gateways', emptyOutDir: true,
    lib: { entry: 'src/main.ts', formats: ['es'], fileName: () => 'gateways.js', cssFileName: 'gateways' },
    rollupOptions: { output: { assetFileNames: '[name][extname]' } }
  }
});
