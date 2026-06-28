#!/usr/bin/env node
/*
 * Confirm the canonical package.json version matches Android versionName and
 * the latest release-notes entry.
 */

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const notes = JSON.parse(fs.readFileSync(path.join(root, 'release-notes.json'), 'utf8'));
const gradle = fs.readFileSync(path.join(root, 'android', 'app', 'build.gradle.kts'), 'utf8');

const versionName = gradle.match(/versionName\s*=\s*"([^"]+)"/)?.[1];
const latestRelease = notes.releases?.[0]?.version;
const errors = [];

if (!versionName) errors.push('Could not read Android versionName.');
if (versionName && versionName !== pkg.version) {
  errors.push(`Android versionName ${versionName} does not match package.json ${pkg.version}.`);
}
if (!latestRelease) errors.push('release-notes.json has no releases[0].version.');
if (latestRelease && latestRelease !== pkg.version) {
  errors.push(`Latest release-notes version ${latestRelease} does not match package.json ${pkg.version}.`);
}

if (errors.length > 0) {
  console.error(errors.join('\n'));
  process.exit(1);
}

console.log(`Version sync OK: ${pkg.version}`);
