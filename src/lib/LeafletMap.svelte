<script lang="ts">
	import type { Map } from 'leaflet';
	import type { GetMapOptions } from './types';

	import { onMount, createEventDispatcher, onDestroy } from 'svelte';

	import L_marker_icon from 'leaflet/dist/images/marker-icon.png';
	import L_marker_icon_2x from 'leaflet/dist/images/marker-icon-2x.png';
	import L_marker_shadow from 'leaflet/dist/images/marker-shadow.png';

	let map_html: HTMLDivElement;

	let className: string = '';
	export { className as class };
	export let map_options: GetMapOptions = () => ({});
	export let L: typeof import('leaflet');
	export let map: Map;

	const dispatch = createEventDispatcher();

	onMount(async () => {
	  L = await import('leaflet');

	  const GestureHandling = await import('leaflet-gesture-handling');
	  L.Map.addInitHook('addHandler', 'gestureHandling', GestureHandling.GestureHandling);

	  L.Icon.Default.prototype.options.iconUrl = L_marker_icon;
	  L.Icon.Default.prototype.options.iconRetinaUrl = L_marker_icon_2x;
	  L.Icon.Default.prototype.options.shadowUrl = L_marker_shadow;
	  L.Icon.Default.imagePath = '';

	  let options = {
	    ...map_options(L),
	    gestureHandling: true
	  };

	  map = new L.Map(map_html, options);

	  dispatch('ready');
	});

	onDestroy(() => {
	  if (map) map.remove();
	});
</script>

<div class="leaflet-map {className}" bind:this={map_html}></div>

<style>
	.leaflet-map {
		height: 80vh;
		width: 100%;
	}
</style>
