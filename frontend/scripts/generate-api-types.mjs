#!/usr/bin/env node
/**
 * Generate the typed API client from the running backend's OpenAPI schema.
 *
 * The console's request and response shapes are **not** hand-copied from the
 * Python source: they are generated from `/openapi.json`, so a change to a
 * Pydantic model cannot drift away from the client without the generator
 * failing. The generated file is committed; this script regenerates it.
 *
 * Usage:
 *   npm run api:types                       # against http://127.0.0.1:8000
 *   API_BASE_URL=http://host:8000 npm run api:types
 *
 * The backend only serves `/openapi.json` when `APP_ENV=development`, so
 * this script is a development-time tool.
 */
import { mkdirSync, writeFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import openapiTS, { astToString } from "openapi-typescript"

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, "..")
const OUT = resolve(ROOT, "src/lib/api/schema.ts")

const API_BASE = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "")

const url = `${API_BASE}/openapi.json`
process.stdout.write(`Fetching ${url} ... `)

let schema
try {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`)
  }
  schema = await response.json()
} catch (error) {
  process.stderr.write(
    `\nCould not fetch the OpenAPI schema: ${error.message}\n` +
      `Is the API running in development mode (APP_ENV=development)?\n`,
  )
  process.exit(1)
}
process.stdout.write("ok\n")

const temporary = resolve(ROOT, "node_modules/.cache/openapi.json")
mkdirSync(dirname(temporary), { recursive: true })
writeFileSync(temporary, JSON.stringify(schema, null, 2), "utf8")

const ast = await openapiTS(schema, { alphabetize: true, silent: true })
mkdirSync(dirname(OUT), { recursive: true })
writeFileSync(OUT, astToString(ast), "utf8")

process.stdout.write(`Wrote ${OUT}\n`)
