// Shared helpers for the Pages Functions read-API. These run on Cloudflare's edge
// and talk to Neon over its serverless HTTP driver — no separate API host.
import { neon } from "@neondatabase/serverless";

export interface Env {
  // Neon connection string. Stored as the SQLAlchemy `postgresql+psycopg://…` form
  // (one secret shared with the Python side); we strip the driver suffix for neon().
  DATABASE_URL: string;
}

export const getSql = (env: Env) =>
  neon(env.DATABASE_URL.replace("+psycopg", ""));

export const json = (data: unknown, status = 200): Response =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
