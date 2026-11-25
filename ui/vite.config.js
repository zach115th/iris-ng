import { defineConfig } from "vite";
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { svelte } from '@sveltejs/vite-plugin-svelte'

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


function resolveInputs(directory) {
    const inputs = fs
        .readdirSync(directory, { withFileTypes: true, })
        .reduce((acc, entry) => {
            if (entry.isFile()) {
                const file = entry.name;
                const filename = path.parse(file).name;
                const filepath = path.join(directory, file);

                acc[filename] = fileURLToPath(new URL(filepath, import.meta.url));
            } else {
                const subDirectory = entry.name;
                const filepath = path.join(directory, subDirectory, 'index.js');

                if (fs.existsSync(filepath)) {
                    acc[subDirectory] = fileURLToPath(new URL(filepath, import.meta.url));
                }
            }

            return acc;
        }, {});

    return inputs;
}

export default defineConfig(({ mode }) => {
    const production = (mode === 'production');
    const development = (mode === 'development');


    return {
        build: {
            minify: false,
            manifest: false,
            outDir: 'dist',
            rollupOptions: {
                input: resolveInputs('./src/pages'),
                output: {
                    manualChunks: undefined,
                    entryFileNames: 'assets/js/iris/[name].js',
                    chunkFileNames: 'assets/js/chunks/[name]-[hash].js',
                    assetFileNames: 'assets/[ext]/[name].[ext]',
                },
                treeshake: false,
            },
            sourcemap: (development) ? 'inline': false,
        },
        resolve: {
            alias: {
                '$lib': path.resolve('./src/lib'),
            },
        },
        plugins: [
            svelte({
                emitCss: false,
                inspector: development,
            }),
            viteStaticCopy({
                targets: [
                    // Core
                    {
                        src: 'node_modules/bootstrap/dist/js/bootstrap.min.js',
                        dest: 'assets/js/core',
                    },
                    {
                        src: 'node_modules/jquery/dist/jquery.min.js',
                        dest: 'assets/js/core',
                        rename: 'jquery.3.2.1.min.js',
                    },
                    {
                        src: 'node_modules/jquery-validation/dist/jquery.validate.min.js',
                        dest: 'assets/js/core',
                        rename: 'jquery.validate.js',
                    },
                    {
                        src: 'node_modules/popper.js/dist/umd/popper.min.js',
                        dest: 'assets/js/core',
                    },
                    {
                        src: 'node_modules/socket.io/client-dist/socket.io.min.js',
                        dest: 'assets/js/core',
                        rename: 'socket.io.js',
                    },
                    {
                        // Chart.js 4's UMD build (it sets window.Chart, as 2.x's Chart.min.js did)
                        src: 'node_modules/chart.js/dist/chart.umd.min.js',
                        dest: 'assets/js/core',
                        rename: 'charts.js',
                    },
                    // Plugins
                    {
                        // The OFFICIAL minified build of the same ace-builds
                        // version, renamed so the template URLs (hardcoded to
                        // .../ace/src-noconflict/) stay untouched. ace.js goes
                        // 886K -> 464K, which is mostly parse-time on every
                        // case page; modes/themes/workers ship in both dirs.
                        src: 'node_modules/ace-builds/src-min-noconflict/',
                        dest: 'assets/js/plugin/ace/',
                        rename: 'src-noconflict',
                    },
                    {
                        // dropzone 6 dropped dist/min/; its browser build is
                        // dist/dropzone-min.js. Shipped under the name the
                        // pipelines modal actually loads (dropzone.js) - the
                        // old dropzone.min.js copy was never referenced by any
                        // template, so the modal's script tag 404'd before
                        // this copy. A second copy under the old name, kept
                        // for anything external, went on 2026-11-25: nothing
                        // loaded it.
                        src: 'node_modules/dropzone/dist/dropzone-min.js',
                        dest: 'assets/js/plugin/dropzone/',
                        rename: 'dropzone.js',
                    },
                    {
                        src: 'node_modules/html2canvas/dist/html2canvas.min.js',
                        dest: 'assets/js/plugin/html2canvas/',
                    },
                    {
                        src: 'node_modules/jquery.scrollbar/jquery.scrollbar.min.js',
                        dest: 'assets/js/plugin/jquery-scrollbar/',
                    },
                    {
                        src: 'node_modules/jquery-ui-touch-punch/jquery.ui.touch-punch.min.js',
                        dest: 'assets/js/plugin/jquery-ui-touch-punch/',
                    },
                    {
                        src: 'node_modules/marked/lib/marked.umd.js',
                        dest: 'assets/js/plugin/marked/',
                        rename: 'marked.min.js',
                    },
                    {
                        src: 'node_modules/vis-network/standalone/umd/vis-network.min.js',
                        dest: 'assets/js/plugin/vis/',
                    },
                    {
                        src: 'node_modules/vis-timeline/standalone/umd/vis-timeline-graph2d.min.js',
                        dest: 'assets/js/plugin/vis/',
                        rename: 'vis.graph.js'
                    },
                    {
                        src: 'node_modules/xss/dist/xss.min.js',
                        dest: 'assets/js/plugin/xss/',
                        rename: 'xss.js',
                    },
                ]
            }),
        ],
    }
});
