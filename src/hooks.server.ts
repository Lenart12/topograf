import { error, type Handle, type HandleServerError } from "@sveltejs/kit";
import notFoundLimiter from "$lib/scan_protection";

export const handle: Handle = async ({ event, resolve }) => {
  if (await notFoundLimiter.isLimited(event)) {
    console.error('Rate limit exceeded [404]:', event.getClientAddress(), event.url.pathname);
    return error(429, 'Preveč zahtev');
  }

  return await resolve(event);
}

export const handleError: HandleServerError = async ({ error, event, status, message }) => {
  if (status === 404) {
    if (await notFoundLimiter.check(event)) {
      console.error("Rate limit exceeded for IP:", event.getClientAddress());
    }
  }
  console.error(error)
}