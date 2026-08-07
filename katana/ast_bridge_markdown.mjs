import fs from "node:fs"

import { importOptional } from "./ast_bridge_modules.mjs"

function markdownNodeSummary(root) {
  const counts = {}
  let nodes = 0
  let maxDepth = 0
  function visit(value, depth) {
    if (!value || typeof value !== "object") {
      return
    }
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, depth))
      return
    }
    const type = typeof value.type === "string" ? value.type : null
    if (type) {
      nodes += 1
      maxDepth = Math.max(maxDepth, depth)
      counts[type] = (counts[type] || 0) + 1
    }
    for (const [key, child] of Object.entries(value)) {
      if (key !== "position" && key !== "loc" && key !== "source") {
        visit(child, type ? depth + 1 : depth)
      }
    }
  }
  visit(root, 0)
  return { node_count: nodes, max_depth: maxDepth, node_types: counts }
}

export async function parseMarkdownDocument(filePath) {
  const parser = await importOptional("@tanstack/markdown/parser", filePath)
  if (!parser || typeof parser.parseMarkdown !== "function") {
    throw new Error("@tanstack/markdown parser is not available")
  }
  const text = fs.readFileSync(filePath, "utf8")
  const ast = parser.parseMarkdown(text)
  return {
    parser: {
      parser: "tanstack_markdown_ast",
      strategy: "tanstack_parse_markdown",
      precision: "document_ast_without_source_locations",
      available: true,
    },
    document: markdownNodeSummary(ast),
  }
}
