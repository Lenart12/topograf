<script lang="ts">
	import type { CreatedMapConf } from '$lib/types';
	import type { PageData } from './$types';
	import { onMount } from 'svelte';

	export let data: PageData;
	let pdf_viewer: HTMLObjectElement;
	const title =
		data.map_config.naslov1 || `Karta za orientacijo ${new Date().toLocaleDateString()}`;

	type MapPropertyValue = string | number | boolean;
	type MapProperty = [keyof CreatedMapConf, string, (v: MapPropertyValue) => string];
	const map_properties = [
		['map_w', 'Zahodna meja', (v: MapPropertyValue) => `e=${v}m`],
		['map_s', 'Južna meja', (v: MapPropertyValue) => `n=${v}m`],
		['map_e', 'Vzhodna meja', (v: MapPropertyValue) => `e=${v}m`],
		['map_n', 'Severna meja', (v: MapPropertyValue) => `n=${v}m`],
		['target_scale', 'Merilo', (v: MapPropertyValue) => `1:${v}`],
		['naslov1', 'Naslov (prva vrstica)', (v: MapPropertyValue) => v],
		['naslov2', 'Naslov (druga vrstica)', (v: MapPropertyValue) => v],
		['dodatno', 'Dodatno', (v: MapPropertyValue) => v],
		['epsg', 'Koordinatni sistem', (v: MapPropertyValue) => v],
		['edge_wgs84', 'WGS84 na robu', (v: MapPropertyValue) => (v ? 'Da' : 'Ne')]
	] as MapProperty[];

	const pdf_aspect_ratio = data.map_config.map_size_w_m / data.map_config.map_size_h_m;
	const resize_pdf = () => {
		if (!pdf_viewer) return;
		const pdf_width = pdf_viewer.clientWidth;
		const toolbar_height = 32;
		const pdf_height = pdf_width / pdf_aspect_ratio + toolbar_height;
		pdf_viewer.height = `${pdf_height}px`;
	};

	let naslovi = [] as String[];
	if (data.map_config.naslov1) naslovi.push(data.map_config.naslov1);
	if (data.map_config.naslov2) naslovi.push(data.map_config.naslov2);
	const naslov = naslovi
		.join(' - ')
		.substring(0, 60)
		.replace(/[^a-zA-Z0-9À-ž\- ]/g, '_');

	onMount(() => {
		pdf_viewer.onload = resize_pdf;
		window.onresize = resize_pdf;
	});
</script>

<svelte:head>
	<title>Topograf - {title}</title>
</svelte:head>

<main>
	<div class="container mx-auto p-0 md:p-8">
		<div class="card inline-block w-full p-0 md:p-8">
			<div class="card-header">
				<h1 class="h1"><iconify-icon icon="material-symbols:map"></iconify-icon> {title}</h1>
				<h2 class="h2">{data.map_config.naslov2}</h2>
			</div>

			<div class="flex flex-row gap-8 flex-wrap px-4">
				<div>
					<a
						class="btn variant-filled-primary"
						href="{data.map_config.id}/map.pdf"
						download="{naslov}.pdf"
						>Prenesi<iconify-icon icon="material-symbols:download-2"></iconify-icon></a
					>
				</div>
				{#if data.map_cp_report_exists}
					<div>
						<a
							class="btn variant-filled-primary"
							href="{data.map_config.id}/cp_report.pdf"
							download="{naslov}_KT.pdf"
							>Prenesi kontrolne točke<iconify-icon icon="material-symbols:download-2"
							></iconify-icon></a
						>
					</div>
				{/if}
				<div>
					<h3 class="h3">
						Podatki <iconify-icon icon="mdi:information-slab-box-outline"></iconify-icon>
					</h3>
					<div class="flex flex-wrap gap-2">
						{#each map_properties as [prop, label, format]}
							{#if data.map_config[prop]}
								<div>
									<strong>{label}:</strong>
									{format(data.map_config[prop])}
								</div>
							{/if}
						{/each}
					</div>
					<object
						bind:this={pdf_viewer}
						width="100%"
						height="600"
						type="application/pdf"
						title={naslov}
						data="{data.map_config.id}/map.pdf"
					></object>
				</div>
			</div>
		</div>
	</div>
</main>
