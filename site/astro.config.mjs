// @ts-check
import { defineConfig } from "astro/config";

// En production (GitHub Actions), SITE_URL et BASE_PATH sont fournis par le workflow :
//   SITE_URL=https://pseudo.github.io  BASE_PATH=/manifcarte
export default defineConfig({
  site: process.env.SITE_URL || "http://localhost:4321",
  base: process.env.BASE_PATH || "/",
  trailingSlash: "always",
  build: { format: "directory" },
  devToolbar: { enabled: false },
});
