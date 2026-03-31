/* ═══════════════════════════════════════════════════════════
   GridFront Detect — HUD Controller
   HUD DOM updates, alert banner logic, connection status
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.hud = (function() {
  var alertBanner = document.getElementById('alert-banner');
  var statusDot = document.getElementById('status-dot');
  var headerSubtitle = document.getElementById('machine-subtitle') || document.querySelector('#header .subtitle');

  // Find or create FPS display in the HUD
  var fpsEl = document.getElementById('api-fps');
  if (!fpsEl) {
    var hud = document.getElementById('hud');
    if (hud) {
      var item = document.createElement('div');
      item.className = 'hud-item';
      item.innerHTML = '<span class="label">API FPS</span><span class="value" id="api-fps">--</span>';
      hud.appendChild(item);
      fpsEl = document.getElementById('api-fps');
    }
  }

  // Status text — update the label inside the first hud-item
  var statusLabel = null;
  if (statusDot && statusDot.parentElement) {
    statusLabel = statusDot.parentElement; // the <span class="label"> containing the dot
  }

  function update(stats) {
    // People / equipment / markers counts
    var peopleEl = document.getElementById('people-count');
    var equipEl = document.getElementById('equip-count');
    var markerEl = document.getElementById('marker-count');
    if (peopleEl) peopleEl.textContent = stats.people;
    if (equipEl) equipEl.textContent = stats.equip;
    if (markerEl) markerEl.textContent = stats.markers;

    // Nearest distance
    var nearestEl = document.getElementById('nearest-dist');
    if (nearestEl) {
      var zone = stats.zone || (stats.closestDist < 3.5 ? 'DANGER' : stats.closestDist < 6 ? 'WARNING' : 'CLEAR');
      nearestEl.textContent = stats.closestDist < Infinity ? stats.closestDist.toFixed(1) + 'm' : '\u2014';
      nearestEl.style.color = zone === 'DANGER' ? '#EF4444' : zone === 'WARNING' ? '#F59E0B' : '#22c55e';
    }

    // Connection status dot and label
    var m = stats.mode || 'Mock';
    var modeLabel = m === 'Mock' ? 'SIM' : 'LIVE';
    if (statusDot) {
      statusDot.className = 'dot dot-green'; // always green — scene is running
    }
    if (statusLabel) {
      // Preserve the dot element, update text
      var dotHtml = statusDot ? statusDot.outerHTML : '';
      statusLabel.innerHTML = dotHtml + modeLabel;
    }

    // API FPS
    if (fpsEl) {
      fpsEl.textContent = stats.fps > 0 ? stats.fps.toFixed(0) : '--';
    }

    // Alert banner
    var zoneState = stats.zone || 'CLEAR';
    if (zoneState === 'DANGER') {
      alertBanner.style.display = 'block';
      var distText = stats.closestDist < Infinity ? stats.closestDist.toFixed(1) + 'm' : '--';
      alertBanner.textContent = 'DANGER \u2014 Object at ' + distText;
      if (statusDot) statusDot.className = 'dot dot-red';
    } else {
      alertBanner.style.display = 'none';
    }

    // Header subtitle — show zone state
    if (headerSubtitle) {
      var base = 'CAT 950 GC \u2014 Wheel Loader #1';
      if (zoneState === 'DANGER') {
        headerSubtitle.textContent = base + ' \u2022 DANGER ZONE';
        headerSubtitle.style.color = '#EF4444';
      } else if (zoneState === 'WARNING') {
        headerSubtitle.textContent = base + ' \u2022 WARNING';
        headerSubtitle.style.color = '#F59E0B';
      } else {
        headerSubtitle.textContent = base + ' \u2022 Clear';
        headerSubtitle.style.color = '#A6A6A6';
      }
    }

    // Re-grab statusDot after innerHTML update
    statusDot = document.getElementById('status-dot');
  }

  return {
    update: update
  };
})();
