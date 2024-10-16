<script lang="ts">
	import '../app.postcss';
	import { AppShell, AppBar } from '@skeletonlabs/skeleton';
	import { LightSwitch } from '@skeletonlabs/skeleton';
	import logo_scukabarvno from '$lib/assets/logo-scukabarvno.png';
	import github_mark from '$lib/assets/github-mark.svg';
</script>

<!-- App Shell -->
<AppShell>
	<svelte:fragment slot="header">
		<!-- App Bar -->
		<AppBar>
			<svelte:fragment slot="lead">
				<a href="/">
					<strong class="text-xl">Topograf</strong>
				</a>
				<a href="https://scuke.si">
					<img src={logo_scukabarvno} alt="SCUKE" class="h-8 px-2" />
				</a>
			</svelte:fragment>
			<svelte:fragment slot="trail">
				<LightSwitch />
				<a
					class="btn h-6 p-3 variant-filled-surface"
					href="https://github.com/Lenart12/topograf"
					target="_blank"
					rel="noreferrer"
				>
					<img src={github_mark} alt="GitHub" class="h-5" />
				</a>
			</svelte:fragment>
		</AppBar>
	</svelte:fragment>
	<!-- Page Route Content -->
	<slot />
</AppShell>
