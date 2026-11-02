#!/usr/bin/env node
// Print "name@version" for every package found under a node_modules tree
// (nested ones included), sorted, one per line. Used to explain a difference
// between two builds: if the sets differ, the dependency resolution differed.
//
// usage: node list-deps.js <path-to-node_modules>
const fs = require('fs')
const path = require('path')

const root = process.argv[2]
if (!root) {
  console.error('usage: node list-deps.js <path-to-node_modules>')
  process.exit(2)
}

const seen = new Set()

function visitNodeModules(dir) {
  let entries
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const e of entries) {
    if (e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.name.startsWith('@') && e.isDirectory()) {
      visitNodeModules(full)
      continue
    }
    if (!e.isDirectory() && !e.isSymbolicLink()) continue
    visitPackage(full)
  }
}

function visitPackage(dir) {
  let pkg
  try {
    pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'))
  } catch {
    return
  }
  if (pkg.name && pkg.version) seen.add(`${pkg.name}@${pkg.version}`)
  visitNodeModules(path.join(dir, 'node_modules'))
}

visitNodeModules(root)
for (const line of [...seen].sort()) console.log(line)
