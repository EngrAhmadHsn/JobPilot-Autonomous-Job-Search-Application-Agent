// Mirrors ZCode's skill frontmatter parser (zcode.cjs: _3s / v3s / b3s / S3s)
// and reports skills whose frontmatter would fail to load.
//
// ZCode's parser treats a value as a multi-line block ONLY when it is exactly
// ">", "|", ">-", "|+" (optionally with a chomp marker). A bare
// "description:" followed by an indented block is NOT a block: the value is the
// empty string and the indented lines are skipped as "indented keys are
// ignored". An empty description means the skill is dropped.
//
// A skill fails to load when name is missing, description is missing/empty, or
// description exceeds 1024 characters.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join } from "node:path";

const MAX_DESCRIPTION = 1024;

function parseFrontmatter(text) {
  const body = text.replace(/^﻿/, "");
  if (!body.startsWith("---")) return null;
  const lines = body.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") return null;
  const end = lines.findIndex((l, i) => i > 0 && l.trim() === "---");
  if (end <= 0) return null;

  const values = {};
  const block = lines.slice(1, end);
  let i = 0;
  while (i < block.length) {
    const line = block[i] ?? "";
    if (line.trim().length === 0 || line.trim().startsWith("#") || /^\s/.test(line)) {
      i += 1;
      continue;
    }
    const colon = line.indexOf(":");
    if (colon <= 0) {
      i += 1;
      continue;
    }
    const key = line.slice(0, colon).trim();
    const raw = line.slice(colon + 1).trim();

    if (/^>[+-]?$/.test(raw) || /^\|[+-]?$/.test(raw)) {
      const folded = raw.startsWith(">");
      i += 1;
      const parts = [];
      while (i < block.length) {
        const l = block[i] ?? "";
        if (l.trim().length > 0 && !/^\s/.test(l)) break;
        parts.push(l);
        i += 1;
      }
      const indents = parts
        .filter((l) => l.trim().length > 0)
        .map((l) => /^(\s*)/.exec(l)?.[1]?.length ?? 0);
      const a = indents.length ? Math.min(...indents) : 0;
      const stripped = parts.map((l) => (l.trim().length === 0 ? "" : l.slice(a).trim()));
      values[key] = folded
        ? stripped.filter(Boolean).join(" ")
        : stripped.join("\n").trim();
    } else {
      values[key] = raw;
      i += 1;
    }
  }
  return values;
}

function unquote(v) {
  if (v === undefined) return "";
  const t = v.trim();
  if (t.length !== 0 && ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'")))) {
    return t.slice(1, -1).trim();
  }
  return t;
}

const roots = process.argv.slice(2);
const problems = [];
let checked = 0;

for (const root of roots) {
  let entries;
  try {
    entries = readdirSync(root);
  } catch {
    continue;
  }
  for (const name of entries) {
    const dir = join(root, name);
    if (!statSync(dir).isDirectory()) continue;
    const file = join(dir, "SKILL.md");
    let text;
    try {
      text = readFileSync(file, "utf8");
    } catch {
      problems.push([`${root}/${name}`, "missing SKILL.md"]);
      continue;
    }
    checked += 1;
    const fm = parseFrontmatter(text);
    if (!fm) {
      problems.push([`${root}/${name}`, "no frontmatter block"]);
      continue;
    }
    const nameValue = unquote(fm.name);
    if (!nameValue) problems.push([`${root}/${name}`, "missing name"]);
    const description = unquote(fm.description);
    if (!description) {
      problems.push([`${root}/${name}`, "EMPTY description (skill is dropped)"]);
    } else if (description.length > MAX_DESCRIPTION) {
      problems.push([`${root}/${name}`, `description ${description.length} chars > ${MAX_DESCRIPTION}`]);
    }
  }
}

if (problems.length === 0) {
  console.log(`OK: ${checked} skill(s) checked, all loadable`);
} else {
  console.log(`PROBLEMS in ${problems.length} of ${checked} skill(s):`);
  for (const [where, why] of problems) console.log(`  ${where} -> ${why}`);
  process.exitCode = 1;
}
