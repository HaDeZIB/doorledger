import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // do not auto-write AGENTS.md / CLAUDE.md into the project on `next dev`
  agentRules: false,
  // keep the dev-mode badge out of demo recordings
  devIndicators: false,
};

export default nextConfig;
