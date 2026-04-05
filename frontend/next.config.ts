import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // IMPORTANT: start the dev server with --hostname 127.0.0.1 (see package.json dev script).
  //
  // Without it, Next.js binds to 0.0.0.0. When the browser accesses the app via the
  // LAN IP (192.168.x.x), getSocketUrl() derives the HMR WebSocket URL from
  // window.location.hostname, producing ws://192.168.x.x:3001/_next/webpack-hmr.
  // That WebSocket repeatedly fails → after 12 reconnects Next.js calls
  // window.location.reload(), creating a ~40s forced-reload loop that interrupts
  // every useEffect data fetch before it can update state.

  async rewrites() {
    // In Docker the API container is reachable via service name (API_INTERNAL_URL).
    // Locally it runs on host port 8001.
    const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8001";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
