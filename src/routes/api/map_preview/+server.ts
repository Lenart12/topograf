import fs from 'node:fs';
import { RateLimiter } from 'sveltekit-rate-limiter/server';
import { MapPreviewRequest } from '$lib/api/validation';
import { runCreateMapPy } from '$lib/api/execute';
import { dev } from '$app/environment';
import { MapPreviewProgress, ProgressError } from '$lib/api/progress_tracker';

const limiter = new RateLimiter({
  IP: [40, 'h'],
  IPUA: [5, 'm'],
});

export async function POST(event) {
  console.log('POST /api/map_preview');
  const { request } = event;

  let validated: MapPreviewRequest;
  try {
    validated = await MapPreviewRequest.validate(await request.formData());
  } catch (error) {
    let error_message = '';
    if (error instanceof Error) error_message = error.message;
    else error_message = `${error}`;
    console.log('Bad request:', error_message);
    return new Response(error_message, { status: 400 });
  }

  const preflight = event.url.searchParams.get('preflight') === 'true';
  if (preflight) {
    console.log(`[${validated.id}] Preflight for map create`);
    return new Response(validated.id);
  }

  const pt = MapPreviewProgress.addRun(validated.id);
  const [pt_progress, pt_message, pt_error] = pt;
  pt_message('Začetek obdelave');

  console.log(`[${validated.id}] Request for map preview`);

  const output_file = `${validated.output_folder}/map_previews/${validated.id}.png`;

  if (fs.existsSync(output_file)) {
    console.log('Returning cached image');
    pt_progress(90);
    pt_message('Karta je že narejena');
    const png = await fs.promises.readFile(output_file);
    pt_progress(100);
    MapPreviewProgress.finishRun(validated.id);
    return new Response(png, { headers: { 'Content-Type': 'image/png' } });
  }

  if (await limiter.isLimited(event)) {
    if (dev) console.log('Rate limited');
    else {
      pt_progress(100);
      pt_error('Preveč zahtev');
      console.log('Rate limited from', event.getClientAddress());
      MapPreviewProgress.finishRun(validated.id);
      return new Response("Preveč zahtev", { status: 429 });
    }
  }

  try {
    await runCreateMapPy(validated, ...pt);
    const png = await fs.promises.readFile(output_file);
    return new Response(png, { headers: { 'Content-Type': 'image/png' } });
  } catch (error) {
    if (error instanceof ProgressError) {
      console.error(`[${validated.id}] Progress error: ${error.message}`);
      return new Response(error.message, { status: 400 });
    }
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  } finally {
    MapPreviewProgress.finishRun(validated.id);
  }
}
