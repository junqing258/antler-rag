// Mirrors the backend's new_request_id() (timestamp + random suffix) so logs from
// both sides share one sortable format. crypto.getRandomValues is available in
// every context, including plain HTTP served from a LAN address.
export function requestId(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  const random = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${stamp}_${random}`;
}
