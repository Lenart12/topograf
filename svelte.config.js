import adapter from '@sveltejs/adapter-auto';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import fs from 'fs';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	extensions: ['.svelte'],
	// Consult https://kit.svelte.dev/docs/integrations#preprocessors
	// for more information about preprocessors
	preprocess: [vitePreprocess()],

	kit: {
		adapter: {
			name: 'adapter-node+copy',
			adapt: async (...args) => {
				await adapter().adapt(...args);
				fs.copyFileSync('src/server.js', 'build/server.js');
			},
		},
	},
};
export default config;