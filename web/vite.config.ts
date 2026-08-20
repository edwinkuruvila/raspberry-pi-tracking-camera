import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

function requiredEnv(name: string) {
  const value = process.env[name];

  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }

  return value;
}

function requiredListEnv(name: string) {
  const values = requiredEnv(name)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  if (values.length === 0) {
    throw new Error(`Environment variable must contain at least one value: ${name}`);
  }

  return values;
}
export default defineConfig(({ command }) => {
  const apiUpstream = command === "serve" ? requiredEnv("ROOMCAM_API_UPSTREAM") : "http://api:8000";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      allowedHosts: command === "serve" ? requiredListEnv("ROOMCAM_ALLOWED_HOSTS") : [],
      proxy: {
        "/api": {
          target: apiUpstream,
          changeOrigin: false,
        },
        ...(command === "serve"
          ? {
              [requiredEnv("ROOMCAM_PUBLIC_WEBRTC_URL")]: {
                target: apiUpstream,
                changeOrigin: false,
              },
            }
          : {}),
      },
    },
  };
});
