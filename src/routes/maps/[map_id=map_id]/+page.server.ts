import type { PageServerLoad } from './$types';
import fs from 'node:fs';
import { TEMP_FOLDER } from '$env/static/private';
import { error } from '@sveltejs/kit';
import type { CreatedMapConf } from '$lib/types';
import notFoundLimiter from "$lib/scan_protection";

export const load = (async (event) => {
  const { map_id } = event.params;
  // Load map pdf and config
  const map_path = `${TEMP_FOLDER}/maps/${map_id}`;

  if (!fs.existsSync(map_path)) {
    if (await notFoundLimiter.check(event)) {
      console.error('Rate limit exceeded [404]:', event.getClientAddress(), event.url.pathname);
      throw error(429, 'Preveč zahtev');
    }
    return error(404, `Karta z ID ${map_id} ne obstaja`);
  }
  const request_origin = new URL(event.request.url).origin;

  const map_config = JSON.parse((await fs.promises.readFile(`${map_path}/conf.json`)).toString()) as CreatedMapConf;
  const map_cp_report_exists = fs.existsSync(`${map_path}/cp_report.pdf`)
  return { request_origin, map_config, map_cp_report_exists };
}) satisfies PageServerLoad;