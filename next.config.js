/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow the frontend to call the FastAPI backend during development
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
