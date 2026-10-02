/** Retry only an authentication rejection, with the same request body/id. */
export async function fetchAuthenticated(
  url: string, init: RequestInit, token: string,
  resolveToken: (token: string, force: boolean) => Promise<string>,
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  let current = await resolveToken(token, false);
  const send = () => {
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${current}`);
    return fetcher(url, {...init, headers});
  };
  const response = await send();
  if (response.status !== 401) return response;
  await response.body?.cancel();
  current = await resolveToken(current, true);
  return send();
}
