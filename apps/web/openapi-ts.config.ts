import { defineConfig } from "@hey-api/openapi-ts";

// Generated from the FastAPI OpenAPI document; never edit src/lib/api by hand.
// Refresh: npm run gen:api
export default defineConfig({
  input: "openapi.json",
  output: "src/lib/api",
  plugins: ["@hey-api/client-fetch", "@tanstack/react-query"],
});
