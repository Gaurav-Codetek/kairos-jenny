import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the dev badge clear of the sidebar footer.
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://127.0.0.1:8888/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;
