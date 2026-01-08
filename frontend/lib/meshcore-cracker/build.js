import * as esbuild from 'esbuild';

await esbuild.build({
  entryPoints: ['src/index.ts'],
  bundle: true,
  format: 'esm',
  outfile: 'dist/index.js',
  sourcemap: true,
  target: 'es2020',
  platform: 'browser',
  external: [],
  minify: false,
});

console.log('Build complete: dist/index.js');
