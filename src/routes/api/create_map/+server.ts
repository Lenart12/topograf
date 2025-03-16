import fs from 'node:fs';
import { RateLimiter } from 'sveltekit-rate-limiter/server';
import { MapCreateRequest } from '$lib/api/validation.js';
import { runCreateMapPy } from '$lib/api/execute.js';
import { TEMP_FOLDER } from '$env/static/private';
import { dev } from '$app/environment';

const limiter = new RateLimiter({
  IP: [10, 'h'],
  IPUA: [2, 'm'],
});

export async function POST(event) {
  console.log('POST /api/create_map');
  const { request } = event;

  let validated: MapCreateRequest;
  try {
    validated = await MapCreateRequest.validate(await request.formData());
  } catch (error) {
    let error_message = '';
    if (error instanceof Error) error_message = error.message;
    else error_message = `${error}`;
    console.log('Bad request:', error_message);
    return new Response(error_message, { status: 400 });
  }
  console.log(`[${validated.id}] Request for map create`);

  const maps_folder = `${TEMP_FOLDER}/maps`;
  if (!fs.existsSync(maps_folder)) await fs.promises.mkdir(maps_folder);
  else if (fs.existsSync(`${maps_folder}/${validated.id}/map.pdf`)) {
    console.log(`Using cached map`);
    return new Response(validated.id);
  }

  if (await limiter.isLimited(event) && false) {
    if (dev) console.log('Rate limited');
    else return new Response("Preveč zahtev", { status: 429 });
  }

  try {
    await runCreateMapPy(validated);
    console.log(`[${validated.id}] Map created`);
    return new Response(validated.id);
  } catch (error) {
    console.error(error);
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  } finally {
    if (validated.slikal && fs.existsSync(validated.slikal)) await fs.promises.unlink(validated.slikal);
    if (validated.slikad && fs.existsSync(validated.slikad)) await fs.promises.unlink(validated.slikad);
  }
}
