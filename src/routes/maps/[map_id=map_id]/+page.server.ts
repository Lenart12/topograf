import type { PageServerLoad } from './$types';
import fs from 'node:fs';
import { TEMP_FOLDER } from '$env/static/private';
import { error } from '@sveltejs/kit';
import type { CreatedMapConf } from '$lib/types';

export const load = (async ({ params }) => {
  const { map_id } = params;
  // Load map pdf and config
  const map_path = `${TEMP_FOLDER}/maps/${map_id}`;

  if (!fs.existsSync(map_path)) {
    return error(404, `Karta z ID ${map_id} ne obstaja`);
  }

  const map_pdf = await fs.promises.readFile(`${map_path}/map.pdf`);
  const map_config = JSON.parse((await fs.promises.readFile(`${map_path}/conf.json`)).toString()) as CreatedMapConf;
  return { map_pdf: [...map_pdf], map_config };
}) satisfies PageServerLoad;