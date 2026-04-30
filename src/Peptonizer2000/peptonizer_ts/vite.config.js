import { defineConfig } from "vite";
import path from "path";
import dts from 'vite-plugin-dts';

export default defineConfig({
    assetsInclude: ['**/*.py', '**/*.whl'],
    worker: {
        format: "es"
    },
    build: {
        lib: {
            entry: path.resolve(__dirname, 'src/index.ts'), // Change this to your library's entry point
            name: 'Peptonizer', // The global variable name for IIFE/UMD builds
            formats: ['es'], // Switch to ESM format,
            filename: "peptonizer.js"
        },
        rollupOptions: {
            // Externalize dependencies you don't want to bundle
            external: ['pyodide'], // Example, add others like 'react' if neededp
            output: {
                globals: {
                    pyodide: 'Pyodide', // Define the global name for external libraries
                }
            }
        },
    },
    plugins: [
        // Use `vite-plugin-dts` for type bundling
        dts({
            outputDir: 'dist', // Where to output the `.d.ts` file
            insertTypesEntry: true, // Automatically add the "types" field in `package.json`
            rollupTypes: true, // Enable bundling all `.d.ts` files into a single file
        }),
    ],
    optimizeDeps: { exclude: ["pyodide"] }
});
