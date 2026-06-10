/* One-off visual check for the P4 cab-display demo parity work.
 * Uses the platform repo's Playwright install. Captures the cab display in
 * each scene state plus the simulated walk-through.
 *   node scripts/screenshot-cab-demo.js
 */
const path = require('path');
const fs = require('fs');
const { chromium } = require(
  'C:/Users/helve/platform.gridfront.io/GridFront/node_modules/playwright'
);

const OUT = 'C:/Users/helve/Desktop/scout-demo-screens';

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  page.on('pageerror', (e) => console.error('PAGE ERROR:', e.message));
  await page.goto('http://127.0.0.1:5555/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#cab-display');
  await page.waitForTimeout(2500); // config/zones/coverage fetches

  const frame = await page.$('.cab-display-frame');

  // State 0 — clear scene, idle wordmark.
  await page.evaluate(() => updateCabDisplay([]));
  await page.waitForTimeout(400);
  await frame.screenshot({ path: path.join(OUT, '0-clear.png') });

  // Synthetic detections straight down the front camera's centreline.
  const shot = async (z, name) => {
    await page.evaluate((zm) => {
      updateCabDisplay([{ track_id: 'shot', label: 'person', x_m: 0.4, z_m: zm, distance_m: zm }]);
    }, z);
    await page.waitForTimeout(400);
    await frame.screenshot({ path: path.join(OUT, name) });
  };
  await shot(10.5, '1-distance.png'); // beyond zones -> People in Distance
  await shot(5.0, '2-warning.png');   // inside warning band
  await shot(2.0, '3-danger.png');    // inside danger band

  // Simulated walk-through, mid-walk frame + full page for context.
  await page.evaluate(() => { updateCabDisplay([]); cabSimToggle(); });
  await page.waitForTimeout(5000);
  await frame.screenshot({ path: path.join(OUT, '4-sim-walkthrough.png') });
  await page.screenshot({ path: path.join(OUT, '5-full-page.png') });

  const states = await page.evaluate(() => ({
    coverage: cabCoverage.length,
    machine: cabMachine,
    state: cabSceneState,
    palette: CAB_SCENE_PAL[cabSceneState],
  }));
  console.log('final state:', JSON.stringify(states));
  await browser.close();
  console.log('screenshots written to', OUT);
})();
