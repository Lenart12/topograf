<script lang="ts">
	import type { CreatedMapConf } from '$lib/types';
	import type { PageData } from './$types';
	import { onMount } from 'svelte';

	export let data: PageData;
	let pdf_viewer: HTMLObjectElement;
	let download_button: HTMLAnchorElement;
	const title =
		data.map_config.naslov1 || `Karta za orientacijo ${new Date().toLocaleDateString()}`;

	type MapProperty = [keyof CreatedMapConf, string, (v: any) => string];
	const map_properties = [
		['map_w', 'Zahodna meja', (v: any) => `e=${v}m`],
		['map_s', 'Južna meja', (v: any) => `n=${v}m`],
		['map_e', 'Vzhodna meja', (v: any) => `e=${v}m`],
		['map_n', 'Severna meja', (v: any) => `n=${v}m`],
		['target_scale', 'Merilo', (v: any) => `1:${v}`],
		['naslov1', 'Naslov (prva vrstica)', (v: any) => v],
		['naslov2', 'Naslov (druga vrstica)', (v: any) => v],
		['dodatno', 'Dodatno', (v: any) => v],
		['epsg', 'Koordinatni sistem', (v: any) => v],
		['edge_wgs84', 'WGS84 na robu', (v: any) => (v ? 'Da' : 'Ne')]
	] as MapProperty[];

	const pdf_aspect_ratio = data.map_config.map_size_w_m / data.map_config.map_size_h_m;
	const resize_pdf = () => {
		if (!pdf_viewer) return;
		const pdf_width = pdf_viewer.clientWidth;
		const toolbar_height = 32;
		const pdf_height = pdf_width / pdf_aspect_ratio + toolbar_height;
		pdf_viewer.height = `${pdf_height}px`;
		console.log(pdf_height);
	};

	onMount(() => {
		const pdf_blob = new Blob([new Uint8Array(data.map_pdf)], { type: 'application/pdf' });
		const pdf_url = URL.createObjectURL(pdf_blob);
		pdf_viewer.data = pdf_url;
		download_button.href = pdf_url;
		download_button.download = `${data.map_config.naslov1}.pdf`;

		pdf_viewer.onload = resize_pdf;
		window.onresize = resize_pdf;

		return () => {
			URL.revokeObjectURL(pdf_url);
		};
	});
</script>

<svelte:head>
	<title>Topograf - {title}</title>
</svelte:head>

<main>
	<div class="container mx-auto p-0 md:p-8">
		<div class="card inline-block w-full p-0 md:p-8">
			<div class="card-header">
				<h1 class="h1">{title}</h1>
				<h2 class="h2">{data.map_config.naslov2}</h2>
			</div>

			<div class="flex flex-row gap-8 flex-wrap px-4">
				<div>
					<a class="btn variant-filled-primary" bind:this={download_button} href="#invalid"
						>Prenesi karto</a
					>
				</div>
				<div class="flex flex-wrap gap-2">
					{#each map_properties as [prop, label, format]}
						{#if data.map_config[prop]}
							<div>
								<strong>{label}:</strong>
								{format(data.map_config[prop])}
							</div>
						{/if}
					{/each}
					<object
						bind:this={pdf_viewer}
						width="100%"
						height="600"
						type="application/pdf"
						title={data.map_config.naslov1}
					></object>
				</div>
			</div>
		</div>
	</div>
</main>
