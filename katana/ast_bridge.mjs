#!/usr/bin/env node
import fs from "node:fs"
import path from "node:path"
import {
  importOptional,
  loadOptional,
  resolveImportOptional,
  resolveOptional,
} from "./ast_bridge_modules.mjs"

function lineOf(sourceFile, position) {
  return sourceFile.getLineAndCharacterOfPosition(position).line + 1
}

function firstLine(text) {
  return text.split(/\r?\n/).find((line) => line.trim())?.trim() || ""
}

function sourceKind(ts, filePath) {
  switch (path.extname(filePath)) {
    case ".tsx":
      return ts.ScriptKind.TSX
    case ".jsx":
      return ts.ScriptKind.JSX
    case ".js":
    case ".mjs":
    case ".cjs":
      return ts.ScriptKind.JS
    default:
      return ts.ScriptKind.TS
  }
}

function textCodeLines(text) {
  return text.split(/\r?\n/).filter((line) => line.trim()).length
}

function slugSymbol(value, fallback) {
  const slug = value.replace(/[^0-9A-Za-z_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase()
  if (!slug || /^[0-9]/.test(slug)) {
    return fallback
  }
  return slug
}

function scanImports(ts, sourceFile) {
  const modules = []
  for (const statement of sourceFile.statements) {
    if (
      ts.isImportDeclaration(statement) &&
      statement.moduleSpecifier &&
      ts.isStringLiteral(statement.moduleSpecifier)
    ) {
      modules.push(statement.moduleSpecifier.text)
    }
  }
  return modules
}

function fileMeta(ts, sourceFile, filePath) {
  const modules = scanImports(ts, sourceFile)
  const shadcnImports = modules
    .map((item) => item.match(/^(?:@\/)?components\/ui\/([^"']+)$/)?.[1])
    .filter(Boolean)
    .sort()
  const uiPrimitiveImports = modules
    .map((item) => item.match(/^@radix-ui\/(.+)$/)?.[1])
    .filter(Boolean)
    .sort()
  const basename = path.basename(filePath)
  const parts = new Set(path.resolve(filePath).split(path.sep))
  const nextConvention =
    [
      "page.tsx",
      "page.jsx",
      "layout.tsx",
      "layout.jsx",
      "loading.tsx",
      "loading.jsx",
      "error.tsx",
      "error.jsx",
      "not-found.tsx",
      "not-found.jsx",
      "route.ts",
      "route.js",
    ].includes(basename) && (parts.has("app") || parts.has("pages"))
  const firstLines = sourceFile.text.split(/\r?\n/).slice(0, 5).map((line) => line.trim().replace(/;$/, ""))
  return {
    import_modules: modules,
    imports_react: modules.includes("react"),
    imports_next: modules.some((item) => item === "next" || item.startsWith("next/")),
    next_convention: nextConvention,
    use_client: firstLines.includes('"use client"') || firstLines.includes("'use client'"),
    shadcn_imports: [...new Set(shadcnImports)],
    ui_primitive_imports: [...new Set(uiPrimitiveImports)],
  }
}

function exported(ts, node) {
  return Boolean(
    ts.canHaveModifiers(node) &&
      ts.getModifiers(node)?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword),
  )
}

function defaultExported(ts, node) {
  return Boolean(
    ts.canHaveModifiers(node) &&
      ts.getModifiers(node)?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword),
  )
}

function declarationEntries(ts, sourceFile) {
  const entries = []
  for (const statement of sourceFile.statements) {
    if (
      ts.isFunctionDeclaration(statement) ||
      ts.isClassDeclaration(statement) ||
      ts.isInterfaceDeclaration(statement) ||
      ts.isTypeAliasDeclaration(statement) ||
      ts.isEnumDeclaration(statement)
    ) {
      if (!statement.name && !defaultExported(ts, statement)) {
        continue
      }
      entries.push({
        node: statement,
        name: statement.name?.text || "default_export",
        kind: ts.SyntaxKind[statement.kind],
      })
      continue
    }
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name)) {
          entries.push({
            node: statement,
            bodyNode: declaration,
            name: declaration.name.text,
            kind: ts.SyntaxKind[statement.declarationList.kind],
          })
        }
      }
    }
  }
  return entries
}

function collectIdentifierRefs(ts, node, names, self) {
  const refs = new Set()
  function visit(child) {
    if (ts.isIdentifier(child) && child.text !== self && names.has(child.text)) {
      refs.add(child.text)
    }
    ts.forEachChild(child, visit)
  }
  ts.forEachChild(node, visit)
  return [...refs].sort()
}

function hasJsx(ts, node) {
  let found = false
  function visit(child) {
    if (found) {
      return
    }
    if (
      ts.isJsxElement(child) ||
      ts.isJsxSelfClosingElement(child) ||
      ts.isJsxFragment(child)
    ) {
      found = true
      return
    }
    ts.forEachChild(child, visit)
  }
  visit(node)
  return found
}

function childEntry(ts, sourceFile, node, name, kind, tags = []) {
  const text = node.getText(sourceFile)
  return {
    name,
    kind,
    signature: firstLine(text),
    start_line: lineOf(sourceFile, node.getStart(sourceFile)),
    end_line: lineOf(sourceFile, node.getEnd()),
    code_lines: textCodeLines(text),
    tags,
    meta: {},
  }
}

function collectTsChildren(ts, sourceFile, node) {
  const children = []
  if (ts.isClassDeclaration(node)) {
    for (const member of node.members) {
      if (
        (ts.isMethodDeclaration(member) ||
          ts.isConstructorDeclaration(member) ||
          ts.isGetAccessorDeclaration(member) ||
          ts.isSetAccessorDeclaration(member)) &&
        member.name
      ) {
        const name = ts.isConstructorDeclaration(member)
          ? "constructor"
          : member.name.getText(sourceFile)
        children.push(childEntry(ts, sourceFile, member, name, ts.SyntaxKind[member.kind], ["method"]))
      }
    }
    return children
  }

  function visit(child) {
    if (child === node) {
      ts.forEachChild(child, visit)
      return
    }
    if (ts.isFunctionDeclaration(child) && child.name) {
      children.push(childEntry(ts, sourceFile, child, child.name.text, "FunctionDeclaration", ["nested_function"]))
      return
    }
    if (ts.isFunctionExpression(child) || ts.isArrowFunction(child)) {
      const parent = child.parent
      let name = null
      if (ts.isVariableDeclaration(parent) && ts.isIdentifier(parent.name)) {
        name = parent.name.text
      } else if (ts.isPropertyAssignment(parent)) {
        name = parent.name.getText(sourceFile)
      }
      if (name) {
        const tags = []
        if (/^handle[A-Z0-9]/.test(name) || /^on[A-Z0-9]/.test(name)) {
          tags.push("handler")
        }
        if (/^render[A-Z0-9]/.test(name)) {
          tags.push("render_helper")
        }
        if (hasJsx(ts, child)) {
          tags.push("jsx")
        }
        children.push(childEntry(ts, sourceFile, child, name, ts.SyntaxKind[child.kind], tags))
        return
      }
    }
    ts.forEachChild(child, visit)
  }
  ts.forEachChild(node, visit)
  return children.sort((left, right) => left.start_line - right.start_line)
}

function tailwindMeta(ts, node) {
  const classes = []
  let className = 0
  let cn = 0
  let cva = 0
  function addText(value) {
    for (const item of value.split(/\s+/)) {
      if (item.trim()) {
        classes.push(item.trim())
      }
    }
  }
  function visit(child) {
    if (
      ts.isJsxAttribute(child) &&
      child.name.text === "className" &&
      child.initializer
    ) {
      className += 1
      if (ts.isStringLiteral(child.initializer)) {
        addText(child.initializer.text)
      }
    }
    if (ts.isCallExpression(child)) {
      const expression = child.expression
      const callName = ts.isIdentifier(expression) ? expression.text : ""
      if (callName === "cn") {
        cn += 1
      }
      if (callName === "cva") {
        cva += 1
      }
      if (callName === "cn" || callName === "cva" || callName === "twMerge") {
        for (const arg of child.arguments) {
          if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) {
            addText(arg.text)
          }
        }
      }
    }
    ts.forEachChild(child, visit)
  }
  visit(node)
  return {
    className,
    cn,
    cva,
    classes: [...new Set(classes)].sort(),
  }
}

function enrichTsSymbol(ts, sourceFile, fileMetaPayload, entry, names) {
  const node = entry.node
  const text = node.getText(sourceFile)
  const bodyNode = entry.bodyNode || node
  const tags = []
  const meta = {
    exported: exported(ts, node),
    default_export: defaultExported(ts, node),
    type_only: ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node),
  }
  const isPascal = /^[A-Z][A-Za-z0-9]*$/.test(entry.name)
  if (isPascal && hasJsx(ts, bodyNode)) {
    tags.push("react_component")
  }
  if (/^use[A-Z0-9]/.test(entry.name)) {
    tags.push("react_hook")
  }
  if (fileMetaPayload.use_client) {
    tags.push("client_component")
    meta.use_client = true
  }
  if (fileMetaPayload.imports_next || fileMetaPayload.next_convention) {
    tags.push("next")
    if (fileMetaPayload.next_convention) {
      meta.next_convention = true
    }
  }
  const tailwind = tailwindMeta(ts, bodyNode)
  if (tailwind.className || tailwind.cn || tailwind.cva || tailwind.classes.length) {
    tags.push("tailwind")
    meta.tailwind = tailwind
  }
  if (fileMetaPayload.shadcn_imports.length) {
    tags.push("shadcn")
    meta.shadcn_imports = fileMetaPayload.shadcn_imports
  }
  if (fileMetaPayload.ui_primitive_imports.length) {
    tags.push("ui_primitive")
    meta.ui_primitive_imports = fileMetaPayload.ui_primitive_imports
  }
  if (fileMetaPayload.imports_react) {
    meta.imports_react = true
  }
  return {
    name: entry.name,
    kind: entry.kind,
    signature: firstLine(text),
    start_line: lineOf(sourceFile, node.getStart(sourceFile)),
    end_line: lineOf(sourceFile, node.getEnd()),
    code_lines: textCodeLines(text),
    references: collectIdentifierRefs(ts, bodyNode, names, entry.name),
    tags: [...new Set(tags)],
    meta,
    children: collectTsChildren(ts, sourceFile, bodyNode),
  }
}

function outlineTypeScript(filePath) {
  const ts = loadOptional("typescript", filePath)
  if (!ts) {
    throw new Error("typescript module is not available")
  }
  const text = fs.readFileSync(filePath, "utf8")
  const sourceFile = ts.createSourceFile(
    filePath,
    text,
    ts.ScriptTarget.Latest,
    true,
    sourceKind(ts, filePath),
  )
  const entries = declarationEntries(ts, sourceFile)
  const names = new Set(entries.map((entry) => entry.name))
  const meta = fileMeta(ts, sourceFile, filePath)
  return {
    parser: {
      parser: "typescript_compiler_ast",
      strategy: "typescript_compiler_api_source_file",
      precision: "semantic_top_level",
      available: true,
      import_modules: meta.import_modules,
    },
    symbols: entries.map((entry) => enrichTsSymbol(ts, sourceFile, meta, entry, names)),
  }
}

function outlineCss(filePath) {
  const postcss = loadOptional("postcss", filePath)
  if (!postcss) {
    throw new Error("postcss module is not available")
  }
  const text = fs.readFileSync(filePath, "utf8")
  const root = postcss.parse(text, { from: filePath })
  const symbols = []
  const used = new Set()
  function dedupe(name) {
    if (!used.has(name)) {
      used.add(name)
      return name
    }
    let index = 2
    while (used.has(`${name}_${index}`)) {
      index += 1
    }
    const next = `${name}_${index}`
    used.add(next)
    return next
  }
  root.nodes?.forEach((node, index) => {
    if (!node.source?.start || !node.source?.end) {
      return
    }
    const isAtRule = node.type === "atrule"
    if (isAtRule && ["charset", "import"].includes(node.name)) {
      return
    }
    const signature = isAtRule ? `@${node.name}${node.params ? ` ${node.params}` : ""}` : node.selector
    if (!signature) {
      return
    }
    const body = text
      .split(/\r?\n/)
      .slice(node.source.start.line - 1, node.source.end.line)
      .join("\n")
    const tags = []
    const meta = {}
    if (/@(?:tailwind|apply|layer|screen)\b/.test(body)) {
      tags.push("tailwind")
      meta.tailwind = {
        directives: [...new Set([...body.matchAll(/@(tailwind|apply|layer|screen)\b/g)].map((match) => match[1]))],
      }
    }
    symbols.push({
      name: dedupe(slugSymbol(signature, `rule_${index + 1}`)),
      kind: isAtRule ? "CssAtRule" : "CssRule",
      signature,
      start_line: node.source.start.line,
      end_line: node.source.end.line,
      code_lines: textCodeLines(body),
      references: [],
      tags,
      meta,
    })
  })
  return {
    parser: {
      parser: "postcss_ast",
      strategy: "postcss_stylesheet_ast",
      precision: "css_ast_rules",
      available: true,
    },
    symbols,
  }
}

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

async function parseMarkdownDocument(filePath) {
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

function capabilities(filePath) {
  return {
    node: Boolean(process.version),
    typescript: Boolean(resolveOptional("typescript", filePath)),
    postcss: Boolean(resolveOptional("postcss", filePath)),
    tanstack_markdown: Boolean(resolveImportOptional("@tanstack/markdown/parser", filePath)),
  }
}

async function main() {
  const [, , command, filePath] = process.argv
  if (!command || !filePath) {
    throw new Error("usage: source_split_ast_bridge.mjs <typescript|css|markdown|capabilities> <file>")
  }
  let payload
  if (command === "typescript") {
    payload = outlineTypeScript(filePath)
  } else if (command === "css") {
    payload = outlineCss(filePath)
  } else if (command === "markdown") {
    payload = await parseMarkdownDocument(filePath)
  } else if (command === "capabilities") {
    payload = capabilities(filePath)
  } else {
    throw new Error(`unknown command: ${command}`)
  }
  process.stdout.write(`${JSON.stringify(payload)}\n`)
}

try {
  await main()
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`)
  process.exit(1)
}
