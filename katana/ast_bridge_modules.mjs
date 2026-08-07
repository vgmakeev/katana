import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { pathToFileURL } from "node:url"

const requireFromHere = createRequire(import.meta.url)

export function resolveOptional(name, sourceFile) {
  const candidates = [
    process.cwd(),
    path.dirname(path.resolve(sourceFile || ".")),
    path.dirname(new URL(import.meta.url).pathname),
  ]
  try {
    return requireFromHere.resolve(name, { paths: candidates })
  } catch {
    return null
  }
}

export function loadOptional(name, sourceFile) {
  const resolved = resolveOptional(name, sourceFile)
  if (!resolved) {
    return null
  }
  return requireFromHere(resolved)
}

export async function importOptional(name, sourceFile) {
  const resolved = resolveImportOptional(name, sourceFile)
  return resolved ? import(pathToFileURL(resolved).href) : null
}

export function resolveImportOptional(name, sourceFile) {
  const parts = name.split("/")
  const scoped = name.startsWith("@")
  const packageParts = parts.slice(0, scoped ? 2 : 1)
  const subpathParts = parts.slice(scoped ? 2 : 1)
  const exportKey = subpathParts.length ? `./${subpathParts.join("/")}` : "."
  const starts = [
    process.cwd(),
    path.dirname(path.resolve(sourceFile || ".")),
    path.dirname(new URL(import.meta.url).pathname),
  ]
  const searched = new Set()
  for (const start of starts) {
    for (let current = path.resolve(start); ; current = path.dirname(current)) {
      if (!searched.has(current)) {
        searched.add(current)
        const packageDir = path.join(current, "node_modules", ...packageParts)
        const manifestPath = path.join(packageDir, "package.json")
        if (fs.existsSync(manifestPath)) {
          try {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"))
            const declared = manifest.exports?.[exportKey]
            const target =
              typeof declared === "string" ? declared : declared?.import || declared?.default
            if (target) {
              return path.resolve(packageDir, target)
            }
          } catch {
            // A malformed optional package is reported as unavailable.
          }
        }
      }
      const parent = path.dirname(current)
      if (parent === current) {
        break
      }
    }
  }
  return null
}
