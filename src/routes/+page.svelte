<script lang="ts">
	// import type { Map, PointExpression } from 'leaflet';
	// import { onMount } from 'svelte';

	import CoordSelector from '$lib/CoordSelector.svelte';
	import { Accordion, AccordionItem } from '@skeletonlabs/skeleton';
	import MapPreview from '$lib/MapPreview.svelte';

	// Konfiguracija
	let velikost: 'a4' | 'a3' = 'a4';
	let postavitev: 'l' | 'p' = 'l';
	let target_scale: number = 25000;

	$: map_size_w_m =
		postavitev == 'l' ? (velikost == 'a4' ? 0.297 : 0.42) : velikost == 'a4' ? 0.21 : 0.297;
	$: map_size_h_m =
		postavitev == 'l' ? (velikost == 'a4' ? 0.21 : 0.297) : velikost == 'a4' ? 0.297 : 0.42;

	let map_center_n: number = 45.79622469212008;
	let map_center_e: number = 14.36317920687543;
	let map_n: number;
	let map_e: number;
	let map_s: number;
	let map_w: number;
	let inside_border: boolean;

	let naslov1: string = 'Karta za orientacijo';
	let naslov2: string = '';
	let dodatno: string = 'Izdelal RJŠ za potrebe orientacije. Karta ni bila reambulirana.';
	let epsg: string = 'EPSG:3794';
	let edge_wgs84: boolean = true;
	let slikal: FileList;
	let slikad: FileList;
	let raster_layer: 'dtk50' | '' = 'dtk50';

	let download_link: HTMLElement;

	let get_map_promise: Promise<any>;
	function get_map() {
		const fd = new FormData();
		fd.append('map_size_w_m', map_size_w_m.toString());
		fd.append('map_size_h_m', map_size_h_m.toString());
		fd.append('map_w', map_w.toString());
		fd.append('map_s', map_s.toString());
		fd.append('map_e', map_e.toString());
		fd.append('map_n', map_n.toString());
		fd.append('target_scale', target_scale.toString());
		fd.append('naslov1', naslov1);
		fd.append('naslov2', naslov2);
		fd.append('dodatno', dodatno);
		fd.append('epsg', epsg);
		fd.append('edge_wgs84', edge_wgs84.toString());
		fd.append('slikal', slikal ? slikal[0] : '');
		fd.append('slikad', slikad ? slikad[0] : '');
		fd.append('raster_layer', raster_layer);

		get_map_promise = (async () => {
			download_link.innerHTML = '';
			const request = fetch('/api/create_map', {
				method: 'POST',
				body: fd
			});

			const response = await request;
			if (!response.ok) {
				const text = await response.text();
				throw new Error(text);
			}

			const map_id = await response.text();
			window.open(`/maps/${map_id}`, '_blank');

			download_link.innerHTML = `<a class="btn variant-filled-primary" href="/maps/${map_id}" target="_blank">Odpri karto</a>`;

			return 'Karta je bila uspešno ustvarjena.';
		})();
	}
</script>

<main>
	<div class="container mx-auto p-8">
		<div class="card inline-block w-full p-8">
			<div class="card-header my-4">
				<h1 class="h1">Ustvari svojo karto</h1>
			</div>

			<p class="lead mt-8 px-4">Klikni na zemljevid ali premakni ročico željene karte.</p>
			<div class="px-4 mt-2">
				<CoordSelector
					bind:map_center_e
					bind:map_center_n
					bind:map_size_w_m
					bind:map_size_h_m
					bind:target_scale
					bind:map_e
					bind:map_n
					bind:map_s
					bind:map_w
					bind:inside_border
				/>
			</div>

			<div class="p-4">
				<Accordion regionControl="variant-soft" regionPanel="variant-soft">
					<AccordionItem open>
						<svelte:fragment slot="summary">
							<h3 class="h3">Postavitev</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<div class="flex flex-row gap-8 flex-wrap">
								<div>
									<h4 class="h4">Velikost</h4>
									<div class="btn-group variant-soft">
										<input hidden type="radio" id="velikost_a4" bind:group={velikost} value="a4" />
										<label
											for="velikost_a4"
											class="p-2"
											class:variant-filled-primary={velikost == 'a4'}>A4</label
										>
										<input hidden type="radio" id="velikost_a3" bind:group={velikost} value="a3" />
										<label
											for="velikost_a3"
											class="p-2"
											class:variant-filled-primary={velikost == 'a3'}>A3</label
										>
									</div>
								</div>

								<div>
									<h4 class="h4">Postavitev karte</h4>
									<div class="btn-group variant-soft">
										<input
											hidden
											type="radio"
											id="postavitev_l"
											bind:group={postavitev}
											value="l"
										/>
										<label
											for="postavitev_l"
											class="p-2"
											class:variant-filled-primary={postavitev == 'l'}>Ležeče</label
										>
										<input
											hidden
											type="radio"
											id="postavitev_p"
											bind:group={postavitev}
											value="p"
										/>
										<label
											for="postavitev_p"
											class="p-2"
											class:variant-filled-primary={postavitev == 'p'}>Pokončno</label
										>
									</div>
								</div>

								<div>
									<h4 class="h4">Merilo</h4>
									<input class="input" type="number" bind:value={target_scale} />
								</div>
							</div>
							<br />
							<p class="lead">
								Sredina karte<sub>WGS84</sub>: lat=<input
									class="input inline-block w-auto"
									type="number"
									step="any"
									bind:value={map_center_n}
								/>
								lon=<input
									class="input inline-block w-auto"
									type="number"
									step="any"
									bind:value={map_center_e}
								/>
							</p>
							{#if map_e && map_n && map_s && map_w}
								<p class="lead">
									Trenutni izrez<sub>D96/TM</sub>: e<sub>min</sub>={map_w} n<sub>min</sub>={map_s},
									e<sub>max</sub>={map_e}, n<sub>max</sub>={map_n}
								</p>
							{/if}
						</svelte:fragment>
					</AccordionItem>
					<AccordionItem open>
						<svelte:fragment slot="summary">
							<h3 class="h3">Označbe</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<h4 class="h4">Naslovi</h4>
							<div>
								<label for="naslov1">Naslov prva vrstica</label>
								<input class="input" id="naslov1" type="text" bind:value={naslov1} />
							</div>

							<div>
								<label for="naslov2">Naslov druga vrstica</label>
								<input class="input" id="naslov2" type="text" bind:value={naslov2} />
							</div>
							<br />
							<h4 class="h4">Dodatno</h4>
							<div>
								<label for="dodatno"
									>Dodatna vrstica (Tretja vrstica v desnem stolpcu na ustvarjeni karti)</label
								>
								<input class="input" id="dodatno" type="text" bind:value={dodatno} />
							</div>
							<br />
							<h4 class="h4">Slike</h4>
							<div>
								<label for="slikal">Slika levo od naslova</label>
								<input
									class="input"
									id="slikal"
									type="file"
									accept="image/png, image/jpeg"
									bind:files={slikal}
								/>
							</div>

							<div>
								<label for="slikad">Slika desno od naslova</label>
								<input
									class="input"
									id="slikad"
									type="file"
									accept="image/png, image/jpeg"
									bind:files={slikad}
								/>
							</div>
						</svelte:fragment>
					</AccordionItem>
					<AccordionItem>
						<svelte:fragment slot="summary">
							<h3 class="h3">Napredne nastavitve</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<div class="space-y-2">
								<h3 class="h3">Koordinatni sistemi</h3>
								<div>
									<label for="epsg">Koordinatni sistem</label>
									<div class="btn-group variant-soft flex-wrap items-stretch">
										<input
											hidden
											type="radio"
											id="epsg_d96_tm"
											bind:group={epsg}
											value="EPSG:3794"
										/>
										<label
											for="epsg_d96_tm"
											class="p-2"
											class:variant-filled-primary={epsg == 'EPSG:3794'}>D96/TM (EPSG:3794)</label
										>
										<input
											hidden
											type="radio"
											id="epsg_d48_gk"
											bind:group={epsg}
											value="EPSG:3912"
										/>
										<label
											for="epsg_d48_gk"
											class="p-2"
											class:variant-filled-primary={epsg == 'EPSG:3912'}>D48/GK (EPSG:3912)</label
										>
										<input
											hidden
											type="radio"
											id="epsg_slovenia_1996"
											bind:group={epsg}
											value="EPSG:8687"
										/>
										<label
											for="epsg_slovenia_1996"
											class="p-2"
											class:variant-filled-primary={epsg == 'EPSG:8687'}
											>Slovenia 1996/ UTM zone 33N (EPSG:8687)</label
										>
										<input
											hidden
											type="radio"
											id="epsg_wgs_84"
											bind:group={epsg}
											value="EPSG:32633"
										/>
										<label
											for="epsg_wgs_84"
											class="p-2"
											class:variant-filled-primary={epsg == 'EPSG:32633'}
											>WGS 84/ UTM zone 33N (EPSG:32633)</label
										>
										<input hidden type="radio" id="epsg_brez" bind:group={epsg} value="Brez" />
										<label for="epsg_brez" class="p-2" class:variant-filled-primary={epsg == 'Brez'}
											>Brez</label
										>
									</div>
								</div>

								<div>
									<label class="flex items-center space-x-2">
										<input class="checkbox" type="checkbox" bind:checked={edge_wgs84} />
										<p>WGS84 koordinatni sistem na robu</p>
									</label>
								</div>
								<label for="raster_layer">
									<h3 class="h3">Rasterski sloj</h3>
								</label>
								<div class="btn-group variant-soft flex-wrap items-stretch">
									<input
										hidden
										type="radio"
										id="raster_dtk50"
										bind:group={raster_layer}
										value="dtk50"
									/>
									<label
										for="raster_dtk50"
										class="p-2"
										class:variant-filled-primary={raster_layer == 'dtk50'}>DTK50 (2014-2023)</label
									>

									<input hidden type="radio" id="raster_brez" bind:group={raster_layer} value="" />
									<label
										for="raster_brez"
										class="p-2"
										class:variant-filled-primary={raster_layer == ''}>Brez</label
									>
								</div>
							</div>
						</svelte:fragment>
					</AccordionItem>
					<AccordionItem>
						<svelte:fragment slot="summary">
							<h3 class="h3">Kontrolne točke</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<MapPreview
								bind:map_w
								bind:map_s
								bind:map_e
								bind:map_n
								bind:raster_layer
								bind:inside_border
							/>
							<h3 class="h3">Kontrolne točke</h3>
							<span class="text-error">WIP</span>
						</svelte:fragment>
					</AccordionItem>
				</Accordion>
			</div>

			<div class="pt-8">
				{#if inside_border === false}
					<div class="variant-filled-error text-center">
						<p>Karta je izven območja DTK50.</p>
					</div>
				{:else}
					<div class="flex justify-center w-100%">
						<button class="btn variant-filled-primary inline-block" on:click={get_map}
							>Ustvari karto</button
						>
					</div>
				{/if}
				{#if get_map_promise}
					{#await get_map_promise}
						<div class="flex justify-center">
							<div class="spinner"></div>
						</div>
					{:then value}
						<div class="variant-filled-info text-center">
							<p>{value}</p>
						</div>
					{:catch error}
						<div class="variant-filled-error text-center">
							<p>Ups, prišlo je do napake.</p>
							<cite>{error.message}</cite>
						</div>
					{/await}
				{/if}
				<div class="flex justify-center w-100%">
					<div bind:this={download_link}></div>
				</div>
			</div>
		</div>
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
</style>
