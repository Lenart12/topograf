import fs from 'node:fs';
import { RateLimiter } from 'sveltekit-rate-limiter/server';
import { MapPreviewRequest } from '$lib/api/validation';
import { runCreateMapPy } from '$lib/api/execute.js';
import { dev } from '$app/environment';
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
  console.log(`[${validated.id}] Request for map preview`);

  const output_file = `${validated.output_folder}/map_previews/${validated.id}.png`;

  if (fs.existsSync(output_file)) {
    console.log('Returning cached image');
    const png = await fs.promises.readFile(output_file);
    return new Response(png, { headers: { 'Content-Type': 'image/png' } });
  }

  if (await limiter.isLimited(event)) {
    if (dev) console.log('Rate limited');
    else {
      console.log('Rate limited from', event.getClientAddress());
      return new Response("Preveč zahtev", { status: 429 });
    }
  }

  try {
    await runCreateMapPy(validated);
    const png = await fs.promises.readFile(output_file);
    return new Response(png, { headers: { 'Content-Type': 'image/png' } });
  } catch (error) {
    console.error(error);
    return new Response("Interna napaka pri ustvarjanju karte", { status: 500 });
  }
}
