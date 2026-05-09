#!/usr/bin/env node
/*
 * Release-notes lint for PRs.
 *
 * User-visible changes should include a humanized pending note in
 * release-notes.json. Internal-only conventional commit prefixes are exempt.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const notesPath = path.join(root, 'release-notes.json');
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

const USER_VISIBLE_PATH_PATTERNS = [
  /^android\/app\/src\/main\/assets\/www\//,
  /^android\/app\/src\/main\/java\//,
  /^android\/app\/src\/main\/res\//,
  /^pipeline\/standalone\//,
  /^models\/[^/]+\.json$/,
];

function fail(message) {
  console.error('');
  console.error('Release-notes lint failed.');
  console.error('');
  console.error(message);
  console.error('');
  console.error('See docs/release-notes-style.md.');
  console.error('');
  process.exit(1);
}

function pass(message) {
  console.log(`release-notes lint: ${message}`);
  process.exit(0);
}

function parseCommitPrefix(subject) {
  if (!subject) return null;
  const match = subject.match(/^(\w+)(?:\([^)]*\))?!?:\s*/);
  return match ? match[1].toLowerCase() : null;
}

function resolveTitle() {
  if (process.env.PR_TITLE && process.env.PR_TITLE.trim()) {
    return process.env.PR_TITLE.trim();
  }
  try {
    return execSync('git log -1 --pretty=%s', { encoding: 'utf8' }).trim();
  } catch {
    return '';
  }
}

function resolveChangedFiles() {
  const localFiles = new Set();
  try {
    const out = execSync('git diff --name-only HEAD', { encoding: 'utf8' });
    out.split('\n').map(line => line.trim().replace(/\\/g, '/')).filter(Boolean)
      .forEach(file => localFiles.add(file));
  } catch {
    // Ignore; committed diff below is still useful in CI.
  }
  try {
    const out = execSync('git ls-files --others --exclude-standard', { encoding: 'utf8' });
    out.split('\n').map(line => line.trim().replace(/\\/g, '/')).filter(Boolean)
      .forEach(file => localFiles.add(file));
  } catch {
    // Ignore; untracked-file listing is only for local convenience.
  }

  const baseRef = process.env.BASE_REF || 'master';
  const candidates = [`origin/${baseRef}`, baseRef, 'gridfront/master'];
  for (const ref of candidates) {
    try {
      const out = execSync(`git diff --name-only ${ref}...HEAD`, {
        encoding: 'utf8',
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      out.split('\n').map(line => line.trim().replace(/\\/g, '/')).filter(Boolean)
        .forEach(file => localFiles.add(file));
      return [...localFiles];
    } catch {
      // Try the next candidate.
    }
  }
  return [...localFiles];
}

function touchesUserVisibleCode(files) {
  return files.some(file => USER_VISIBLE_PATH_PATTERNS.some(pattern => pattern.test(file)));
}

function touchesNotes(files) {
  return files.some(file => file === 'release-notes.json');
}

function pendingHasContent() {
  const notes = JSON.parse(fs.readFileSync(notesPath, 'utf8'));
  const pending = notes.pending;
  if (!Array.isArray(pending) || pending.length === 0) return false;
  return pending.some(note => {
    const hasTitle = note.title && note.title !== DEFAULT_PENDING_TITLE;
    const hasItems = Array.isArray(note.items) && note.items.some(item => String(item).trim());
    return hasTitle || hasItems;
  });
}

function isInitialBaselineRelease() {
  let tags = '';
  try {
    tags = execSync('git tag --list "v*"', { encoding: 'utf8' }).trim();
  } catch {
    tags = '';
  }
  if (tags) return false;

  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const notes = JSON.parse(fs.readFileSync(notesPath, 'utf8'));
  const latest = notes.releases?.[0];
  const hasLatestNote = Array.isArray(latest?.notes) && latest.notes.length > 0;
  return latest?.version === pkg.version && hasLatestNote;
}

const title = resolveTitle();
const prefix = parseCommitPrefix(title);
if (prefix !== null && INTERNAL_ONLY_PREFIXES.has(prefix)) {
  pass(`"${prefix}" is internal-only; release notes are not required.`);
}

const files = resolveChangedFiles();
if (files.length === 0) pass('no file diff detected.');
if (!touchesUserVisibleCode(files)) {
  pass('diff does not touch Android UI/runtime, OAK runtime, or model metadata.');
}

if (!touchesNotes(files)) {
  fail(
    'This change touches user-visible Scout code but does not modify release-notes.json.\n' +
      'Add a short pending note that says what changed for an operator or field tech.'
  );
}

if (!pendingHasContent()) {
  if (isInitialBaselineRelease()) {
    pass('initial baseline release is documented directly in release history.');
  }
  fail('release-notes.json still has the empty pending placeholder.');
}

pass('user-visible change carries a pending release note.');
