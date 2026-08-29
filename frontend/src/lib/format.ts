const pad = (value: number) => String(value).padStart(2, "0");

/** 时间戳：接口给 UTC ISO，界面按本地时区显示到分钟，格式固定不受 locale 影响。 */
export function stamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export function bytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

/** 只在界面上截短，不改动提交给接口的原文。 */
export function clip(text: string, limit: number): string {
  const value = text.trim().replace(/\s+/g, " ");
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}
