const ICON = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#0071e3"/>
  <path d="M11 16.6l3.4 3.4 6.6-7.4" fill="none" stroke="#ffffff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

export function GET() {
  return new Response(ICON, {
    headers: {
      "Cache-Control": "public, max-age=31536000, immutable",
      "Content-Type": "image/svg+xml",
    },
  });
}
