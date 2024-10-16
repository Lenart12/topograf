<script lang="ts">
	import type { LatLngExpression, Map, Marker, Polygon, MapOptions } from 'leaflet';
	import { booleanContains } from '@turf/boolean-contains';
	import proj4 from 'proj4';
	import * as dtk50 from '$lib/dtk50_borders';
	import LeafletMap from './LeafletMap.svelte';

	export let map_center_e: number;
	export let map_center_n: number;
	let _map_center_e: number;
	let _map_center_n: number;

	export let map_size_w_m: number;
	export let map_size_h_m: number;
	export let target_scale: number;

	const map_border_m = [0.011, 0.0141, 0.0195, 0.0143]; // N, E, S, W

	let L: typeof import('leaflet');
	let map: Map;
	let map_center_marker: Marker;
	let map_border: Polygon;

	export let map_n: number;
	export let map_e: number;
	export let map_s: number;
	export let map_w: number;

	export let inside_border: boolean;

	proj4.defs(
		'EPSG:3794',
		'+proj=tmerc +lat_0=0 +lon_0=15 +k=0.9999 +x_0=500000 +y_0=-5000000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs'
	);

	let draw_map_border: () => void;
	let place_marker: (latlng: LatLngExpression) => void;

	const on_map_ready = async () => {
		map.setView([45.7962, 14.3632], 14);

		L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
			maxZoom: 17,
			attribution:
				'Map data: &copy; <a href="https://www.opentopomap.org">OpenTopoMap</a> contributors'
		}).addTo(map);

		// Draw DTK50 border
		const dtk50_polygon = L.polygon(dtk50.dtk50_pages_border);
		map.fitBounds(dtk50_polygon.getBounds());
		map.setMaxBounds(dtk50_polygon.getBounds().pad(0.1));
		map.options.minZoom = map.getZoom();
		const dtk50_polygon_geojson = dtk50_polygon.toGeoJSON();

		// Draw DTK50 border inverted
		function invert_polygon(polygon: LatLngExpression[]): LatLngExpression[][] {
			const whole_world = [
				[-90, -180],
				[90, -180],
				[90, 180],
				[-90, 180]
			];
			const inverted_polygon = [whole_world, polygon] as LatLngExpression[][];
			return inverted_polygon;
		}
		L.polygon(invert_polygon(dtk50.dtk50_pages_border), {
			color: 'red',
			fillColor: 'black',
			fillOpacity: 0.75,
			interactive: false
		}).addTo(map);

		L.polygon([dtk50.dtk50_pages_border, dtk50.dtk50_raster_border], {
			stroke: false,
			fillColor: 'gray',
			fillOpacity: 0.75,
			interactive: false
		}).addTo(map);

		draw_map_border = () => {
			if (!map || !map_center_marker) return;
			const real_size_h_m = (map_size_h_m - map_border_m[0] - map_border_m[2]) * target_scale;
			const real_size_w_m = (map_size_w_m - map_border_m[1] - map_border_m[3]) * target_scale;
			// Convert center to EPSG:3794
			let centerPoint = proj4('EPSG:4326', 'EPSG:3794', [_map_center_e, _map_center_n]);
			let rectangle_polygon = [
				[centerPoint[0] - real_size_w_m / 2, centerPoint[1] - real_size_h_m / 2],
				[centerPoint[0] + real_size_w_m / 2, centerPoint[1] - real_size_h_m / 2],
				[centerPoint[0] + real_size_w_m / 2, centerPoint[1] + real_size_h_m / 2],
				[centerPoint[0] - real_size_w_m / 2, centerPoint[1] + real_size_h_m / 2]
			];
			map_w = Math.round(rectangle_polygon[0][0]);
			map_s = Math.round(rectangle_polygon[0][1]);
			map_e = Math.round(rectangle_polygon[2][0]);
			map_n = Math.round(rectangle_polygon[2][1]);
			let rectangle_latlng = rectangle_polygon.map(
				(point) => proj4('EPSG:3794', 'EPSG:4326', point).reverse() as LatLngExpression
			);
			if (map_border) map.removeLayer(map_border);
			map_border = L.polygon(rectangle_latlng, {
				color: 'black',
				fillColor: 'black',
				fillOpacity: 0.5
			});
			map_border.addTo(map);
			inside_border = booleanContains(dtk50_polygon_geojson, map_border.toGeoJSON());
			if (!inside_border) {
				map_border.setStyle({ color: 'red', fillColor: 'red' });
			}
		};

		place_marker = (latlng: LatLngExpression) => {
			if (map_center_marker) {
				map.removeLayer(map_center_marker);
			}
			map_center_marker = L.marker(latlng, {
				draggable: true
			}).addTo(map);
			map.setView(latlng);
			latlng = map_center_marker.getLatLng();
			_map_center_n = latlng.lat;
			_map_center_e = latlng.lng;
			map_center_n = latlng.lat;
			map_center_e = latlng.lng;
			draw_map_border();
			map_center_marker.on('move', (e) => {
				latlng = map_center_marker.getLatLng();
				_map_center_n = latlng.lat;
				_map_center_e = latlng.lng;
				map_center_n = latlng.lat;
				map_center_e = latlng.lng;
				draw_map_border();
			});
		};

		map.on('click', (e) => {
			place_marker(e.latlng);
		});

		place_marker([map_center_n, map_center_e]);
	};

	$: map_size_w_m && map_size_h_m && target_scale && draw_map_border && draw_map_border();

	$: (map_center_e !== _map_center_e || map_center_n !== _map_center_n) &&
		place_marker &&
		place_marker([map_center_n, map_center_e]);
</script>

<main>
	<LeafletMap bind:map bind:L on:ready={on_map_ready} />
</main>
