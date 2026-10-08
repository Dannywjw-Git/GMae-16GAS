// Parse as ES modules and verify relative imports without executing UI code.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../16gb-ai-studio/vram-console/web');
const walk = dir => fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry =>
  entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.join(dir, entry.name)]);
let errors = 0;
for (const file of walk(root).filter(file => file.endsWith('.js'))) {
  const source = fs.readFileSync(file, 'utf8');
  const result = spawnSync(process.execPath, ['--input-type=module', '--check'], {input: source, encoding: 'utf8'});
  if (result.status !== 0) { console.error(file, result.stderr); errors++; }
  for (const match of source.matchAll(/(?:import|export)\s+(?:[^'";]*?\s+from\s+)?['"](\.[^'"]+)['"]/g)) {
    if (!fs.existsSync(path.resolve(path.dirname(file), match[1]))) {
      console.error('Missing relative import:', file, match[1]); errors++;
    }
  }
}
console.log(`Frontend module errors: ${errors}`);
process.exit(errors ? 1 : 0);
