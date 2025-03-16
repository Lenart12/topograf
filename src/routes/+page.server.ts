import type { PageServerLoad } from "./$types"


export const load = (async (event) => {
  const request_origin = new URL(event.request.url).origin
  return { request_origin }
}) satisfies PageServerLoad;

