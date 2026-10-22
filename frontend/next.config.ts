import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the dev badge clear of the sidebar footer.
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        // Where the API is: local docker compose by default; a deployment sets API_ORIGIN (e.g. https://kairos-api.example.com).
        destination: `${process.env.API_ORIGIN ?? "http://127.0.0.1:8888"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
