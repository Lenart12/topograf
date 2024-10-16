<script lang="ts">
	import type { Map } from 'leaflet';
	import { onMount } from 'svelte';

	export let map_w: number;
	export let map_s: number;
	export let map_e: number;
	export let map_n: number;
	export let raster_layer: string;
	export let inside_border: boolean;

	let preview_promise: Promise<void>;
	let map_preview: HTMLDivElement;
	let initial_text: HTMLDivElement;
	let coordinates_text: HTMLDivElement;

	let L: typeof import('leaflet');
	let map: Map;

	function create_preview() {
		preview_promise = (async () => {
			const fd = new FormData();
			fd.append('map_w', map_w.toString());
			fd.append('map_s', map_s.toString());
			fd.append('map_e', map_e.toString());
			fd.append('map_n', map_n.toString());
			fd.append('raster_layer', raster_layer);
			const res = await fetch('/api/map_preview', {
				method: 'POST',
				body: fd
			});
			if (!res.ok) {
				throw new Error(await res.text());
			}
			const blob = await res.blob();
			const raster_url = URL.createObjectURL(blob);

			map.eachLayer(function (layer) {
				map.removeLayer(layer);
			});

			const map_bounds = L.latLngBounds([
				[map_n, map_w],
				[map_s, map_e]
			]);

			L.imageOverlay(raster_url, map_bounds).addTo(map);
			map.setMaxBounds(map_bounds.pad(0.1));
			map.fitBounds(map_bounds);
			map.setView([(map_n + map_s) / 2, (map_w + map_e) / 2]);

			map.removeEventListener('click');
			map.on('click', function (e) {
				L.marker(e.latlng, {
					title: e.latlng.toString()
				}).addTo(map);
			});

			// Add eProstor attribution
			map.attributionControl.addAttribution(
				'Podatki: <a href="https://www.e-prostor.gov.si">eProstor</a>'
			);
		})();
	}

	onMount(async () => {
		L = await import('leaflet');
		const GestureHandling = await import('leaflet-gesture-handling');
		L.Map.addInitHook('addHandler', 'gestureHandling', GestureHandling.GestureHandling);

		map = L.map(map_preview, {
			// @ts-ignore
			gestureHandling: true,
			crs: L.CRS.Simple,
			minZoom: -5,
			maxZoom: 1
		});

		L.marker([0, 0], {
			icon: L.divIcon({
				className: '',
				html: initial_text
			})
		}).addTo(map);
		map.setView([0, 0], 0);
		map.setMaxBounds([
			[0, 0],
			[0, 0]
		]);
		// @ts-ignore
		L.Control.Coordinates = L.Control.extend({
			onAdd: (map: Map) => {
				coordinates_text = L.DomUtil.create('div');
				coordinates_text.className = 'bg-surface-50 text-surface-900 text-center opacity-100 !m-0';
				coordinates_text.innerHTML = '';
				return coordinates_text;
			},
			onRemove: () => {}
		});
		// @ts-ignore
		L.control.coordinates = (opts: any) => new L.Control.Coordinates(opts);
		// @ts-ignore
		L.control.coordinates({ position: 'bottomleft' }).addTo(map);
		map.on('mousemove', function (e) {
			coordinates_text.innerHTML = `n=${e.latlng.lat.toFixed(0)}, e=${e.latlng.lng.toFixed(0)}`;
		});
	});
</script>

<div class="flex justify-center m-2 gap-2">
	{#if inside_border}
		<button class="btn variant-filled-primary" on:click={create_preview}>Ustvari predogled</button>
	{:else}
		<div class="variant-filled-error text-center">
			<p>Območje ni znotraj meje DTK50.</p>
		</div>
	{/if}

	{#if preview_promise}
		{#await preview_promise}
			<div class="flex justify-center">
				<div class="spinner"></div>
			</div>
		{:catch error}
			<div class="variant-filled-error text-center">
				<p>Ups, prišlo je do napake.</p>
				<cite>{error.message}</cite>
			</div>
		{/await}
	{/if}
</div>

<main>
	<div class="variant-soft" bind:this={map_preview}></div>
	<div hidden>
		<div class="h1 center-transform" bind:this={initial_text}>Klikni na gumb ustvari predogled</div>
	</div>
</main>

<style>
	.spinner {
		display: inline;
		border: 4px solid rgba(0, 0, 0, 0.1);
		border-left-color: #09f;
		border-radius: 50%;
		width: 50px;
		height: 50px;
		animation: spin 1s linear infinite;
	}

	.center-transform {
		position: absolute;
		width: fit-content;
		height: fit-content;
		transform: translate(-50%, -50%);
	}

	main div {
		height: 60vh;
	}
</style>
