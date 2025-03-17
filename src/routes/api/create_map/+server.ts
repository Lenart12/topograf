import fs from 'node:fs';
import { RateLimiter } from 'sveltekit-rate-limiter/server';
import { MapCreateRequest } from '$lib/api/validation.js';
import { runCreateMapPy } from '$lib/api/execute.js';
import { TEMP_FOLDER } from '$env/static/private';
import { CreateMapProgress, ProgressError } from '$lib/api/progress_tracker.js';
import { dev } from '$app/environment';

const limiter = new RateLimiter({
  IP: [20, 'h'],
  IPUA: [5, 'm'],
});

export async function POST(event) {
  console.log('POST /api/create_map');
  const { request } = event;

  const preflight = event.url.searchParams.get('preflight') === 'true';

  let validated: MapCreateRequest;
  try {
    const skip_write_files = preflight;
    validated = await MapCreateRequest.validate(await request.formData(), skip_write_files);
  } catch (error) {
    let error_message = '';
    if (error instanceof Error) error_message = error.message;
    else error_message = `${error}`;
    console.log('Bad request:', error_message);
    return new Response(error_message, { status: 400 });
  }
  if (preflight) {
    console.log(`[${validated.id}] Preflight for map create`);
    return new Response(validated.id);
  }

  const pt = CreateMapProgress.addRun(validated.id);
  const [pt_progress, pt_message, pt_error] = pt;
  pt_message('Začetek obdelave');

  console.log(`[${validated.id}] Request for map create`);

  const maps_folder = `${TEMP_FOLDER}/maps`;
  if (!fs.existsSync(maps_folder)) await fs.promises.mkdir(maps_folder);
  else if (fs.existsSync(`${maps_folder}/${validated.id}/map.pdf`)) {
    console.log(`Using cached map`);
    pt_progress(100);
    pt_message('Karta je že narejena');
    CreateMapProgress.finishRun(validated.id);
    return new Response(validated.id);
  }

  if (await limiter.isLimited(event)) {
    if (dev) console.log('Rate limited');
    else {
      console.log('Rate limited from', event.getClientAddress());
      pt_progress(100);
      pt_error('Preveč zahtev');
      CreateMapProgress.finishRun(validated.id);
      return new Response("Preveč zahtev", { status: 429 });
    }
  }

  try {
    await runCreateMapPy(validated, ...pt);
    console.log(`[${validated.id}] Map created`);
    return new Response(validated.id);
  } catch (error) {
    if (error instanceof ProgressError) {
      console.error(`[${validated.id}] Progress error: ${error.message}`);
      return new Response(error.message, { status: 400 });
    }
    console.error(error);
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  } finally {
    CreateMapProgress.finishRun(validated.id);
    if (validated.slikal && fs.existsSync(validated.slikal)) await fs.promises.unlink(validated.slikal);
    if (validated.slikad && fs.existsSync(validated.slikad)) await fs.promises.unlink(validated.slikad);
  }
}
