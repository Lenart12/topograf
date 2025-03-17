<script lang="ts">
  import type { RequestType } from '$lib/api/validation';
	import { onMount } from 'svelte';
	import type { ProgressProccess } from './api/progress_tracker';
  import { ProgressRadial } from '@skeletonlabs/skeleton';
  export let request_type: RequestType;
  export let progress_id: string;

  let progress: number | undefined = undefined;
  let message = 'Priprava obdelave';

  async function monitor_progress(progress_id: string) {
    if (!progress_id) {
      return;
    }
    console.log('monitor_progress', progress_id);
    let current_progress: ProgressProccess | undefined;
    const progress_url = `/api/${request_type}/${progress_id}/progress`
    for(;;) {
      const progress_request = await fetch(
        progress_url,
        {
          body: current_progress && JSON.stringify(current_progress),
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          }
        }
      );
      if (!progress_request.ok) {
        console.error('Progress fetch failed', progress_request);
        break;
      }
      current_progress = await progress_request.json() as ProgressProccess;
      if (current_progress.progress >= 100) {
        break;
      }
      console.log(current_progress);
      progress = current_progress.progress;
      message = current_progress.message;
    }
  }

  $: monitor_progress(progress_id);
  onMount(() => {
  });
</script>

<div class="flex flex-col items-center gap-4">
  <div class="variant-filled-primary text-center p-2">
    <p>
      <iconify-icon icon="mdi:information"></iconify-icon> {message}
    </p>
  </div>
  <ProgressRadial value={progress} width="w-16" meter="stroke-primary-500"  />
</div>