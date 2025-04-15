import { MapReambulationProgress } from '$lib/api/progress_tracker';

export async function POST(event) {
  return await MapReambulationProgress.handleProgressUpdateRequest(event.params.map_id, await event.request.text());
}