// 与后端的 new_request_id()（时间戳 + 随机后缀）保持一致，
// 使两端的日志共用同一可排序格式。crypto.getRandomValues 在
// 所有上下文中都可用，包括通过局域网地址以纯 HTTP 提供服务时。
export function requestId(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  const random = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${stamp}_${random}`;
}
