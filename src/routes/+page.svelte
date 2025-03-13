<script lang="ts">
	import { debounce } from 'ts-debounce';
	import CoordSelector from '$lib/CoordSelector.svelte';
	import { Accordion, AccordionItem, SlideToggle } from '@skeletonlabs/skeleton';
	import MapPreview from '$lib/MapPreview.svelte';
	import type { ControlPoint, ControlPointJson, ControlPointOptions } from '$lib/types';
	import { get_cp_name } from '$lib';
	import { tick } from 'svelte';

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
	let raster_layer: 'dtk50' | 'dtk25' | 'osm' | 'otm' | '' = 'dtk50';
	let control_points: ControlPoint[] = [];

	let cp_default_color: string = '#ff0000';
	let control_points_size: number = 3;

	let download_link: HTMLElement;

	let get_map_promise: Promise<string>;
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
		fd.append('control_points', create_control_points_json());

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

			download_link.innerHTML = `<a class="btn variant-filled-primary" href="/maps/${map_id}" target="_blank">Odpri karto <iconify-icon icon="mdi:map-search"></iconify-icon></a>`;

			return 'Karta je bila uspešno ustvarjena.';
		})();
	}
	let navodila_open = false;

	let title_edited = false;
	let suggested_title = '';

	const set_title = debounce(async (lat: number, lon: number) => {
		if (isNaN(lat) || isNaN(lon)) return;

		const response = await fetch(
			`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&addressdetails=0&zoom=12`
		);
		const data = await response.json();

		suggested_title = data.name;

		if (suggested_title.length > 30) {
			suggested_title = suggested_title.slice(0, 27) + '...';
		}

		if (title_edited) return;
		naslov1 = suggested_title;
		naslov2 = 'Karta za orientacijo';
	}, 500);
	$: set_title(map_center_n, map_center_e);

	let ask_before_moving: boolean;
	let preview_correct: boolean = false;
	$: ask_before_moving = preview_correct && control_points.length > 0;
	let clear_map_preview: () => void;
	const on_confirmed_move = () => {
		if (clear_map_preview) clear_map_preview();
	};

	function create_control_points_json(add_bounds: boolean = true): string {
		const cp_json = {
			cp_size: control_points_size / 1000,
			cps: control_points.map((cp) => {
				const opts = structuredClone(cp.options);
				opts.name = opts.name === undefined ? '' : opts.name;
				return opts;
			})
		} as ControlPointJson;
		if (add_bounds) {
			cp_json['bounds'] = [map_w, map_s, map_e, map_n];
		}
		return JSON.stringify(cp_json);
	}

	async function import_control_points(event: Event) {
		const input = event.target as HTMLInputElement;
		if (!input.files || input.files.length === 0) return;

		const file = input.files[0];
		const text = await file.text();
		const json = JSON.parse(text);

		if (json.bounds) {
			map_w = json.bounds[0];
			map_s = json.bounds[1];
			map_e = json.bounds[2];
			map_n = json.bounds[3];
			await tick();
			await update_preview();
		}

		control_points_size = json.cp_size * 1000;
		clear_cps();
		for (const cp of json.cps) {
			add_cp(cp);
		}
	}

	let update_preview: () => Promise<void>;
	let clear_cps: () => void;
	let add_cp: (opt: ControlPointOptions) => ControlPoint;
	let remove_cp: (idx: number) => void;
	let swap_cp: (idx1: number, idx2: number) => void;
</script>

<svelte:head>
	<title>Topograf - Ustvaro svojo karto</title>
</svelte:head>

<main>
	<div class="container mx-auto p-0 md:p-8">
		<div class="card inline-block w-full px-0 pb-4 md:p-8">
			<div class="card-header">
				<h1 class="h1">Ustvari svojo karto!</h1>
			</div>

			<div class="px-4 mt-4">
				<Accordion regionControl="variant-soft" regionPanel="variant-soft">
					<AccordionItem bind:open={navodila_open}>
						<svelte:fragment slot="summary">
							<h3 class="h3">
								Navodila <iconify-icon icon="material-symbols:help"></iconify-icon>
							</h3>
							(Klikni tu za {!navodila_open ? 'razširitev' : 'skritje'})
						</svelte:fragment>
						<svelte:fragment slot="content">
							<p class="lead">
								Na zemljevidu izberi želeno območje in nastavitve karte. Klikni na gumb "Ustvari
								karto" in počakaj na rezultat. Ko je karta pripravljena, se bo odprl nov zavihek s
								tvojo karto in tudi pojavil gumb za ogled karte. Če si po ogledu zavovoljen, lahko
								karto potem preneseš ali deliš povezavo do nje, vendar ne računaj na to, da bo
								ostala dostopna za vedno.

								<br /><br />
								Na računalniku lahko zemljevid premikaš z drsenjem miške in povečuješ z vrtenjem kolesca
								ob držanju tipke CTRL oz. CMD. Na mobilnih napravah lahko zemljevid premikaš in povečaš
								samo s potezo dveh prstov.

								<br /><br />
								Izrez izbereš tako, da klikneš na zemljevid kjer ga bo centriralo na izbrano lokacijo.
								Potem ga lahko premikaš s premikom miške med držanjem klika na sredinsko oznako. Tvoja
								izbira bo označena s črnim okvirjem, ki prikazuje izrez karte. Poleg tega je v odseku
								<i>Postavitev</i> možen tudi vnos koordinat sredine izbranega izreza.

								<br /><br />
								Območje vseh listov DTK50 je označeno z rdečo črto. Če je izrez izven območja DTK50,
								se prikazuje opozorilo. Na notranji strani roba tega območja je s sivo obarvano območje,
								ki na DTK50 nima podatkov, vendar je še vedno na listih. Ker ima DTK50 drug koordinatni
								sistem (D96/TM) kot zemljevid, na kateri izbiraš izrez, se bo izrez raztegnil tako, da
								bo pravokoten v TM koordinatnih sistemih. Zato njegov črn okvir ne bo izgledal čisto
								poravnan glede na zemljevid.

								<br /><br />
								V nastavitvah je več odsekov, ki vplivajo na izgled karte. Vsakega se lahko razširi in
								skrije s klikom na naslov odseka, tako kot ta navodila.
							</p>
						</svelte:fragment>
					</AccordionItem>
				</Accordion>
				<div class="mt-2">
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
						bind:ask_before_moving
						on:confirmed_move={on_confirmed_move}
					/>
				</div>
			</div>

			<div class="p-4">
				<Accordion regionControl="variant-soft" regionPanel="variant-soft">
					<AccordionItem open>
						<svelte:fragment slot="summary">
							<h3 class="h3">
								Postavitev <iconify-icon icon="material-symbols:resize"></iconify-icon>
							</h3>
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
											class:variant-filled-primary={postavitev == 'l'}
											><iconify-icon icon="material-symbols:crop-landscape-outline-sharp"
											></iconify-icon></label
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
											class:variant-filled-primary={postavitev == 'p'}
											><iconify-icon icon="material-symbols:crop-portrait-outline-sharp"
											></iconify-icon></label
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
							<h3 class="h3">
								Označbe <iconify-icon icon="material-symbols:text-ad-sharp"></iconify-icon>
							</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<h4 class="h4">Naslovi</h4>
							<div>
								<label for="naslov1">
									<span> Naslov prva vrstica </span>
									{#if title_edited && suggested_title && !naslov1.includes(suggested_title)}
										<span>
											- Predlagan naslov: {suggested_title}
											<button
												class="btn p-0 variant-filled-surface"
												on:click={() => {
													naslov1 = suggested_title;
													title_edited = false;
												}}
											>
												<iconify-icon icon="material-symbols:variable-insert-outline"
												></iconify-icon>
											</button>
										</span>
									{/if}
								</label>
								<input
									class="input"
									id="naslov1"
									type="text"
									bind:value={naslov1}
									on:input={() => {
										title_edited = true;
									}}
								/>
							</div>

							<div>
								<label for="naslov2">Naslov druga vrstica</label>
								<input
									class="input"
									id="naslov2"
									type="text"
									bind:value={naslov2}
									on:input={() => {
										title_edited = true;
									}}
								/>
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
							<h3 class="h3">
								Napredne nastavitve <iconify-icon icon="material-symbols:settings-outline"
								></iconify-icon>
							</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<div class="space-y-2">
								<h3 class="h3">Koordinatni sistemi</h3>
								<div>
									<label for="epsg">Koordinatni sistem karte</label>
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
									<label for="edge_wgs84">
										<p>
											WGS84 koordinatni sistem na robu {edge_wgs84 ? 'vklopljen' : 'izklopljen'}
										</p>
										<div>
											<SlideToggle
												name="edge_wgs84"
												bind:checked={edge_wgs84}
												rounded="rounded-none"
												size="sm"
												active="bg-primary-500"
											/>
										</div>
									</label>
								</div>
								<label for="raster_layer">
									<h3 class="h3">Rasterski sloj</h3>
									{#if preview_correct}
										Menjava rasterskega sloja bo povzročila ponovno stvaritev predogleda karte!
									{/if}
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
									<input
										hidden
										type="radio"
										id="raster_dtk25"
										bind:group={raster_layer}
										value="dtk25"
									/>
									<label
										for="raster_dtk25"
										class="p-2"
										class:variant-filled-primary={raster_layer == 'dtk25'}>DTK25 (1996)</label
									>
									<input
										hidden
										type="radio"
										id="raster_otm"
										bind:group={raster_layer}
										value="otm"
									/>
									<label
										for="raster_otm"
										class="p-2"
										class:variant-filled-primary={raster_layer == 'otm'}>OpenTopoMap</label
									>

									<input
										hidden
										type="radio"
										id="raster_osm"
										bind:group={raster_layer}
										value="osm"
									/>
									<label
										for="raster_osm"
										class="p-2"
										class:variant-filled-primary={raster_layer == 'osm'}>OpenStreetMap</label
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
							<h3 class="h3">
								Kontrolne točke <iconify-icon icon="mdi:map-marker-multiple-outline"></iconify-icon>
							</h3>
						</svelte:fragment>
						<svelte:fragment slot="content">
							<MapPreview
								bind:map_w
								bind:map_s
								bind:map_e
								bind:map_n
								bind:epsg
								bind:raster_layer
								bind:inside_border
								bind:preview_correct
								bind:control_points
								bind:cp_default_color
								bind:update_preview
								bind:clear_preview={clear_map_preview}
								bind:clear_cps
								bind:add_cp
								bind:remove_cp
								bind:swap_cp
							/>
							<h3 class="h3">Kontrolne točke (V IZDELAVI - NI STABILNO ALI 100%)</h3>

							<div class="flex flex-col gap-2">
								<div class="flex flex-row gap-2">
									<label for="control_points_size">Polmer kontrolnih točk (mm)</label>
									<input
										class="w-auto input"
										id="control_points_size"
										type="number"
										step="1"
										bind:value={control_points_size}
									/>
								</div>

								<div class="flex flex-row gap-2 items-center">
									<label for="cp_color_default">Privzeta barva:</label>
									<input
										class="input !rounded-full !h-6 !w-6"
										id="cp_color_default"
										type="color"
										bind:value={cp_default_color}
									/>
								</div>

								{#if control_points.length === 0}
									<p class="lead">Dodaj nove kontrolne točke s klikom na zemljevid.</p>
								{/if}

								<Accordion regionControl="variant-soft" regionPanel="variant-soft">
									{#each control_points as cp, i (cp.id)}
										{@const cp_count = control_points.length}
										{@const is_first = i === 0}
										{@const is_last = i === cp_count - 1}
										<AccordionItem>
											<svelte:fragment slot="summary">
												<div class="flex justify-between flex-wrap">
													<h4 class="h4 whitespace-nowrap">
														<span style:color="gray">#{cp.id}</span>
														{get_cp_name(cp, control_points)}
														<iconify-icon icon="mdi:map-marker"></iconify-icon>
													</h4>
													<div class="inline space-x-2 whitespace-nowrap">
														{#if !is_first}
															<button
																class="btn variant-filled-primary"
																on:click={() => swap_cp(i, i - 1)}
															>
																<iconify-icon icon="mdi:arrow-up"></iconify-icon>
															</button>
														{/if}
														{#if !is_last}
															<button
																class="btn variant-filled-primary"
																on:click={() => swap_cp(i, i + 1)}
															>
																<iconify-icon icon="mdi:arrow-down"></iconify-icon>
															</button>
														{/if}
														<button
															class="btn variant-filled-error"
															on:click={() => remove_cp(cp.id)}
														>
															<iconify-icon icon="mdi:map-marker-remove-variant"></iconify-icon>
														</button>
													</div>
												</div>
											</svelte:fragment>
											<svelte:fragment slot="content">
												<div class="flex flex-col gap-2">
													<div class="flex flex-row gap-2">
														<label for="cp_n_{cp.id}">N:</label>
														<input
															class="w-auto input !bg-surface-500"
															id="cp_n_{cp.id}"
															type="number"
															step="any"
															bind:value={cp.options.n}
														/>
													</div>
													<div class="flex flex-row gap-2">
														<label for="cp_e_{cp.id}">E:</label>
														<input
															class="w-auto input !bg-surface-500"
															id="cp_e_{cp.id}"
															type="number"
															step="any"
															bind:value={cp.options.e}
														/>
													</div>

													<div class="flex flex-row gap-2">
														<label for="cp_name_{cp.id}">Ime:</label>
														<input
															class="flex-1 !bg-surface-500 p-1 w-auto input"
															id="cp_name_{cp.id}"
															type="text"
															placeholder={get_cp_name(cp, control_points)}
															bind:value={cp.options.name}
														/>
													</div>

													<div class="flex flex-row gap-2 items-center">
														<label for="cp_kind_{cp.id}">Vrsta:</label>
														<select
															class="select !bg-surface-500 p-1 w-auto input"
															id="cp_kind_{cp.id}"
															bind:value={cp.options.kind}
														>
															<option value="circle">Krog</option>
															<option value="triangle">Trikotnik</option>
															<option value="dot">Pika</option>
															<option value="point">Točka</option>
															<option value="skip">Preskoči</option>
														</select>
													</div>

													{#if !['skip', 'point'].includes(cp.options.kind)}
														<div class="flex flex-row gap-2 items-center">
															<label for="cp_color_{cp.id}">Barva:</label>
															<input
																class="input !rounded-full !h-6 !w-6"
																id="cp_color_{cp.id}"
																type="color"
																bind:value={cp.options.color}
															/>
														</div>
													{/if}

													{#if cp.options.kind !== 'skip'}
														<div class="flex flex-row gap-2 items-center">
															<label for="cp_connect_next_{cp.id}">Povezava z naslednjim:</label>
															<SlideToggle
																name="cp_connect_next_{cp.id}"
																bind:checked={cp.options.connect_next}
																rounded="rounded-none"
																size="sm"
																active="bg-primary-500"
															/>
														</div>

														{#if cp.options.connect_next}
															<div class="flex flex-row gap-2 items-center">
																<label for="cp_color_line_{cp.id}">Barva povezave:</label>
																<input
																	class="input !rounded-full !h-6 !w-6"
																	id="cp_color_line_{cp.id}"
																	type="color"
																	bind:value={cp.options.color_line}
																/>
															</div>
														{/if}
													{/if}
												</div>
											</svelte:fragment>
										</AccordionItem>
									{/each}
								</Accordion>
								<div class="flex flex-row gap-2">
									{#if control_points.length > 0}
										<button class="btn variant-filled-error" on:click={clear_cps}>
											<iconify-icon icon="mdi:map-marker-remove-variant"></iconify-icon> Odstrani vse
											kontrolne točke
										</button>
										<!-- Izvozi json -->
										<button
											class="btn variant-filled-primary"
											on:click={() => {
												const json = create_control_points_json();
												const blob = new Blob([json], { type: 'application/json' });
												const url = URL.createObjectURL(blob);
												const a = document.createElement('a');
												a.href = url;
												a.download = `kt_${naslov1.replace(/[^a-zA-Z0-9À-ž]/gi, '_')}.json`;
												a.click();
												URL.revokeObjectURL(url);
											}}
										>
											<iconify-icon icon="mdi:file-download"></iconify-icon> Izvozi JSON
										</button>
									{/if}
									<input
										id="import_control_points"
										class="hidden"
										type="file"
										accept="application/json"
										on:change={import_control_points}
									/>
									<label for="import_control_points" class="btn variant-filled-primary">
										<iconify-icon icon="mdi:file-upload"></iconify-icon> Uvozi JSON
									</label>
								</div>
							</div>
						</svelte:fragment>
					</AccordionItem>
				</Accordion>
			</div>

			<div class="pt-8">
				{#if inside_border === false}
					<div class="variant-filled-error text-center">
						<p>
							<iconify-icon icon="material-symbols:error"></iconify-icon>Karta je izven območja
							DTK50.
						</p>
					</div>
				{:else}
					<div class="flex justify-center w-100%">
						<button class="btn variant-filled-primary inline-block" on:click={get_map}
							>Ustvari karto <iconify-icon icon="mdi:map-plus"></iconify-icon></button
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
							<p>
								<iconify-icon icon="material-symbols:error"></iconify-icon>Ups, prišlo je do napake.
							</p>
							<cite
								><iconify-icon icon="material-symbols:chat-error-sharp"></iconify-icon>
								{error.message}</cite
							>
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
