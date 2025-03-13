<script lang="ts">
	import type { Map, LatLng, LatLngLiteral, LatLngTuple, DivIconOptions } from 'leaflet';
	import LeafletMap from './LeafletMap.svelte';
	import type { ControlPoint, GetMapOptions } from './types';
	import { type ControlPointOptions, FormatMapPreviewRequest, type RasterType } from './api/dto';
	import { get_cp_name } from '$lib';
	import { afterUpdate, tick } from 'svelte';

	export let map_w: number;
	export let map_s: number;
	export let map_e: number;
	export let map_n: number;
	export let epsg: string;
	export let raster_type: RasterType;
	export let inside_border: boolean;
	export let preview_correct: boolean;
	export let control_points: ControlPoint[];
	export let cp_default_color: string;

	export let clear_preview: () => void;
	export let update_preview: () => Promise<void>;

	export let clear_cps: () => void;
	export let add_cp: (options: ControlPointOptions) => ControlPoint;
	export let remove_cp: (idx: number) => void;
	export let swap_cp: (idx1: number, idx2: number) => void;

	let _map_w: number;
	let _map_s: number;
	let _map_e: number;
	let _map_n: number;
	let _epsg: string;
	let _raster_type: RasterType;
	let new_cp_id =
		control_points && control_points.length > 0
			? Math.max(...control_points.map((cp) => cp.id)) + 1
			: 0;

	$: preview_correct = _map_w === map_w && _map_s === map_s && _map_e === map_e && _map_n === map_n;

	let preview_promise: Promise<void>;
	let initial_text: HTMLDivElement;
	let coordinates_text: HTMLDivElement;
	let cp_container: HTMLDivElement;

	let L: typeof import('leaflet');
	let map: Map;

	function set_marker(cp: ControlPoint, div_this: HTMLDivElement) {
		if (!L || !map) {
			console.log('set_marker skip', cp, div_this);
			return;
		}
		console.log('set_marker', cp, div_this);
		if (!cp || !div_this) return;

		if (cp.marker) {
			cp.marker.remove();
		}
		cp.marker = L.marker([cp.options.n, cp.options.e], {
			icon: L.divIcon({
				className: '',
				html: div_this,
				iconSize: [0, 0]
			}),
			draggable: true
		}).addTo(map);

		cp.marker.on('drag', function (e) {
			const latlng = e.target.getLatLng();
			cp.options.e = latlng.lng;
			cp.options.n = latlng.lat;
			control_points = [...control_points];
			console.log('drag', cp?.id, latlng);
		});
		return '';
	}

	function add_control_point(latlng: LatLngLiteral) {
		let this_cp_id = new_cp_id++;
		const new_cp = {
			id: this_cp_id,
			marker: null,
			marker_html: null,
			options: {
				e: latlng.lng,
				n: latlng.lat,
				name: undefined,
				kind: control_points.length === 0 ? 'triangle' : 'circle',
				color: cp_default_color,
				color_line: cp_default_color,
				connect_next: true
			}
		} as ControlPoint;

		console.log('add cp', control_points, new_cp);
		control_points = [...control_points, new_cp];
	}

	remove_cp = (idx: number) => {
		const cp = control_points[idx];
		if (!cp) return;

		if (cp.marker) cp.marker.remove();
		if (cp.line_to_next) cp.line_to_next.remove();

		control_points.splice(idx, 1);
		control_points = [...control_points];
	};

	clear_cps = () => {
		control_points.forEach((cp) => {
			if (cp.marker) cp.marker.remove();
			if (cp.line_to_next) cp.line_to_next.remove();
		});
		control_points = [];
	};

	add_cp = (options: ControlPointOptions) => {
		let this_cp_id = new_cp_id++;
		const new_cp = {
			id: this_cp_id,
			marker: null,
			marker_html: null,
			options: {
				e: options.e,
				n: options.n,
				name: options.name,
				kind: options.kind,
				color: options.color,
				color_line: options.color_line,
				connect_next: options.connect_next
			}
		} as ControlPoint;

		console.log('add cp', control_points, new_cp);
		control_points = [...control_points, new_cp];
		return new_cp;
	};

	swap_cp = async (idx1: number, idx2: number) => {
		const cp1 = control_points[idx1];
		const cp2 = control_points[idx2];
		if (!cp1 || !cp2) return;

		// Move all control points idk to cp_container so that hydration works
		control_points.forEach((cp) => {
			console.log('move cp', cp.id, cp.marker_html);
			if (cp.marker_html) cp_container.appendChild(cp.marker_html);
		});

		control_points[idx1] = cp2;
		control_points[idx2] = cp1;
		control_points = [...control_points];

		await tick();
	};

	function create_cp_line(from: LatLngTuple, to: LatLngTuple, col: string) {
		return L.polyline([from, to], {
			color: col
		}).addTo(map);
	}

	async function update_checkpoints(src: string, control_points: ControlPoint[]) {
		if (!L || !map) {
			console.log('check_cp_positions skip', src, control_points);
			return;
		}

		await tick();

		const cp_count = control_points.length;

		console.log('check_cp_positions', src, control_points);
		// Check if all control points are rendered and in correct position
		for (const cp of control_points) {
			console.log('check pos', cp);
			if (!cp.marker_html) {
				console.log('skip pos', cp.id);
				return; // Skip if not yet rendered
			}

			if (!cp.marker || (cp.marker.getIcon().options as DivIconOptions).html !== cp.marker_html) {
				console.log('create cp', src, cp.id, cp.marker_html);
				set_marker(cp, cp.marker_html);
				return;
			}

			if (!map.getContainer().contains(cp.marker_html)) {
				console.log('append cp', src, cp.id, cp.marker_html);
				cp_container.appendChild(cp.marker_html);
				set_marker(cp, cp.marker_html);
				return;
			}

			const latlng = cp.marker.getLatLng();
			if (cp.options.e !== latlng.lng || cp.options.n !== latlng.lat) {
				console.log('move pos', cp.id, cp.options.e, cp.options.n);
				cp.marker.setLatLng([cp.options.n, cp.options.e]);
			} else {
				console.log('same pos', cp.id, cp.options.e, cp.options.n);
			}
		}

		// Link control points
		control_points.forEach((cp, i) => {
			if (!cp.options.connect_next) {
				if (cp.line_to_next) cp.line_to_next.remove();
				cp.line_to_next = null;
				return;
			}

			if (cp_count < 2 || (cp_count == 2 && i == 1)) return;

			let next_cp = control_points[(i + 1) % cp_count];
			if (!next_cp) return;

			const line_from = [cp.options.n, cp.options.e] as LatLngTuple;
			const line_to = [next_cp.options.n, next_cp.options.e] as LatLngTuple;

			if (!cp.line_to_next) {
				cp.line_to_next = create_cp_line(line_from, line_to, cp.options.color_line);
				return;
			}

			if (!map.hasLayer(cp.line_to_next)) {
				cp.line_to_next.addTo(map);
			}

			const latlngs = cp.line_to_next.getLatLngs() as LatLng[];
			if (
				latlngs[0].lat !== line_from[0] ||
				latlngs[0].lng !== line_from[1] ||
				latlngs[1].lat !== line_to[0] ||
				latlngs[1].lng !== line_to[1]
			) {
				cp.line_to_next.setLatLngs([line_from, line_to]);
			}
		});
	}

	afterUpdate(async () => {
		console.log('afterUpdate');
		update_checkpoints('afterupdate', control_points);
	});

	$: update_checkpoints('cpchange', control_points);

	async function update_raster(src: string) {
		console.log('update_raster', src, raster_type, epsg);
		if (preview_correct && _raster_type === raster_type && _epsg === epsg) {
			console.log('update_raster skip', src);
			return;
		}
		preview_promise = (async () => {
			const fd = FormatMapPreviewRequest({
				map_w,
				map_s,
				map_e,
				map_n,
				epsg,
				raster_type
			});
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

			map.off('click');
			map.on('click', function (e) {
				if (preview_correct) add_control_point(e.latlng);
			});

			// Add eProstor attribution
			map.attributionControl.addAttribution(
				'Podatki: <a href="https://www.e-prostor.gov.si">eProstor</a>'
			);

			_map_w = map_w;
			_map_s = map_s;
			_map_e = map_e;
			_map_n = map_n;
			_raster_type = raster_type;
			_epsg = epsg;

			update_checkpoints('update_raster', control_points);
			console.log('update_raster end', src);
		})();

		await preview_promise;
	}

	$: raster_type !== undefined && epsg !== undefined && preview_correct && update_raster('props');

	clear_preview = () => {
		map.eachLayer(function (layer) {
			map.removeLayer(layer);
		});
		map.setView([0, 0], 0);
		map.setMaxBounds([
			[0, 0],
			[0, 0]
		]);
		_map_w = 0;
		_map_s = 0;
		_map_e = 0;
		_map_n = 0;
		L.marker([0, 0], {
			icon: L.divIcon({
				className: '',
				html: initial_text
			})
		}).addTo(map);
	};

	update_preview = async () => {
		return await update_raster('update_preview');
	};

	let map_options: GetMapOptions = (L) => ({
		crs: L.CRS.Simple,
		minZoom: -5,
		maxZoom: 1
	});

	const on_map_ready = async () => {
		console.log('on_map_ready');
		console.log('control_points', control_points);
		console.log('bounds', map_w, map_s, map_e, map_n);

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
		// @ts-expect-error L.Control.Coordinates is not defined as a type but works in runtime
		L.Control.Coordinates = L.Control.extend({
			onAdd: () => {
				coordinates_text = L.DomUtil.create('div');
				coordinates_text.className = 'bg-surface-50 text-surface-900 text-center opacity-100 !m-0';
				coordinates_text.innerHTML = '';
				return coordinates_text;
			},
			onRemove: () => {}
		});
		// @ts-expect-error again...
		L.control.coordinates = (opts: object) => new L.Control.Coordinates(opts);
		// @ts-expect-error again...
		L.control.coordinates({ position: 'bottomleft' }).addTo(map);
		map.on('mousemove', function (e) {
			coordinates_text.innerHTML = `n=${e.latlng.lat.toFixed(0)}, e=${e.latlng.lng.toFixed(0)}`;
		});

		if (map_w && map_s && map_e && map_n) {
			update_raster('on_map_ready');
		}
	};
</script>

<div class="flex justify-center m-2 gap-2">
	{#if inside_border}
		<button class="btn variant-filled-primary" on:click={() => update_raster('btn')}>
			Ustvari predogled
			{#if !preview_correct}
				<iconify-icon icon="mdi:alert-circle" />
			{/if}
		</button>
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
	<LeafletMap class="variant-soft" bind:map bind:L bind:map_options on:ready={on_map_ready} />
	<div hidden>
		<div class="h1 center-transform" bind:this={initial_text}>Klikni na gumb ustvari predogled</div>
		<div bind:this={cp_container}>
			{#each control_points as cp (cp.id)}
				<div class="kt-marker" bind:this={cp.marker_html}>
					<svg
						width="2em"
						viewBox="0 0 14 20"
						xmlns="http://www.w3.org/2000/svg"
						style:color={cp.options.color}
					>
						<path
							fill="currentColor"
							d="M7 9.5A2.5 2.5 0 0 1 4.5 7 2.5 2.5 0 0 1 7 4.5 2.5 2.5 0 0 1 9.5 7 2.5 2.5 0 0 1 7 9.5M7 0a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7"
						/>
					</svg>
					<span class="kt-label whitespace-nowrap">{get_cp_name(cp, control_points)}</span>
				</div>
			{/each}
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

	.center-transform {
		position: absolute;
		width: fit-content;
		height: fit-content;
		transform: translate(-50%, -50%);
	}

	.kt-marker {
		position: absolute;
		transform: translate(-50%, -100%);
	}

	.kt-label {
		position: absolute;
		top: 75%;
		left: 75%;
		color: white;
		text-shadow: 0 0 0.3em black;
	}
</style>
