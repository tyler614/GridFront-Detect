#!/usr/bin/env node
/*
 * Bump GridFront Scout's semantic version, keep Android versionName in sync,
 * and promote pending human release notes when the release is user-visible.
 *
 * Usage:
 *   node scripts/bump-version.js patch
 *   node scripts/bump-version.js minor
 *   node scripts/bump-version.js major
 */

const fs = require('fs');
const path = require('path');

const bump = (process.argv[2] || 'patch').toLowerCase();
if (!['major', 'minor', 'patch'].includes(bump)) {
  console.error('Usage: node scripts/bump-version.js [major|minor|patch]');
  process.exit(1);
}

const root = path.resolve(__dirname, '..');
const pkgPath = path.join(root, 'package.json');
const notesPath = path.join(root, 'release-notes.json');
const gradlePath = path.join(root, 'android', 'app', 'build.gradle.kts');

const DEFAULT_PENDING_TITLE = 'No user-visible changes pending';
const INTERNAL_ONLY_PREFIXES = new Set([
  'chore',
  'test',
  'refactor',
  'ci',
  'docs',
  'build',
  'perf',
  'style',
]);

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeJson(file, value) {
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
}

function parseCommitPrefix(subject) {
  if (!subject) return null;
  const match = subject.match(/^(\w+)(?:\([^)]*\))?!?:\s*/);
  return match ? match[1].toLowerCase() : null;
}

function hasUserVisibleCommit(rawCommits) {
  if (!rawCommits || !rawCommits.trim()) return false;
  const lines = rawCommits.split('\n').map(line => line.trim()).filter(Boolean);
  for (const line of lines) {
    if (line.startsWith('chore: release v') || line.includes('[skip ci]')) continue;
    const prefix = parseCommitPrefix(line);
    if (prefix === null) continue;
    if (!INTERNAL_ONLY_PREFIXES.has(prefix)) return true;
  }
  return false;
}

function pendingHasContent(pending) {
  if (!Array.isArray(pending) || pending.length === 0) return false;
  return pending.some(note => {
    const hasTitle = note.title && note.title !== DEFAULT_PENDING_TITLE;
    const hasItems = Array.isArray(note.items) && note.items.some(item => String(item).trim());
    return hasTitle || hasItems;
  });
}

function nextVersion(current, bumpKind) {
  const parts = current.split('.').map(Number);
  if (parts.length !== 3 || parts.some(n => !Number.isInteger(n) || n < 0)) {
    throw new Error(`Invalid semantic version: ${current}`);
  }
  let [major, minor, patch] = parts;
  if (bumpKind === 'major') {
    major += 1;
    minor = 0;
    patch = 0;
  } else if (bumpKind === 'minor') {
    minor += 1;
    patch = 0;
  } else {
    patch += 1;
  }
  return `${major}.${minor}.${patch}`;
}

function syncGradleVersion(version) {
  let src = fs.readFileSync(gradlePath, 'utf8');
  const codeMatch = src.match(/versionCode\s*=\s*(\d+)/);
  if (!codeMatch) throw new Error('Could not find versionCode in android/app/build.gradle.kts');
  const nextCode = Number(codeMatch[1]) + 1;
  src = src.replace(/versionCode\s*=\s*\d+/, `versionCode = ${nextCode}`);
  src = src.replace(/versionName\s*=\s*"[^"]+"/, `versionName = "${version}"`);
  fs.writeFileSync(gradlePath, src);
  return nextCode;
}

function emptyPending() {
  return [
    {
      title: DEFAULT_PENDING_TITLE,
      kind: 'patch',
      description:
        'Placeholder for the next release. Authors of user-visible changes replace this entry with humanized notes before merging.',
      items: [],
    },
  ];
}

const pkg = readJson(pkgPath);
const notes = readJson(notesPath);
const newVersion = nextVersion(pkg.version, bump);
const today = new Date().toISOString().slice(0, 10);
const hasPending = pendingHasContent(notes.pending);
const userVisible = hasUserVisibleCommit(process.env.RELEASE_COMMITS || '');

if (userVisible && !hasPending) {
  console.error('');
  console.error('Release is user-visible but release-notes.json pending notes are empty.');
  console.error('Add a humanized note to release-notes.json before releasing.');
  console.error('');
  process.exit(1);
}

pkg.version = newVersion;
writeJson(pkgPath, pkg);
const versionCode = syncGradleVersion(newVersion);

if (hasPending) {
  notes.releases = [
    {
      version: newVersion,
      date: today,
      notes: notes.pending,
    },
    ...(Array.isArray(notes.releases) ? notes.releases : []),
  ];
  notes.pending = emptyPending();
  writeJson(notesPath, notes);
  console.log(`Bumped to ${newVersion} (${bump}), Android versionCode ${versionCode}, and promoted pending release notes.`);
} else {
  writeJson(notesPath, notes);
  console.log(`Bumped to ${newVersion} (${bump}), Android versionCode ${versionCode}; no release-notes change.`);
}
