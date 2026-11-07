/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone', // required for Docker Dockerfile
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: 'http://localhost:8000/api/v1/:path*',
      },
    ]
  },
  webpack: (config, { isServer }) => {
    if (isServer) {
      config.resolve = config.resolve || {}
      config.resolve.alias = {
        ...config.resolve.alias,
        'msw/browser': false,
      }
    }
    return config
  },
}

module.exports = nextConfig
