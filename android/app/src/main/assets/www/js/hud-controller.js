/* ═══════════════════════════════════════════════════════════
   GridFront Detect — HUD Controller
   HUD DOM updates, alert banner logic
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.hud = (function() {
  var alertBanner = document.getElementById('alert-banner');

  function update(stats) {
    document.getElementById('people-count').textContent = stats.people;
    document.getElementById('equip-count').textContent = stats.equip;
    document.getElementById('marker-count').textContent = stats.markers;

    var nearestEl = document.getElementById('nearest-dist');
    var zone = stats.closestDist < 3.5 ? 'danger' : stats.closestDist < 6 ? 'warning' : 'safe';
    nearestEl.textContent = stats.closestDist.toFixed(1) + 'm';
    nearestEl.style.color = zone === 'danger' ? '#EF4444' : zone === 'warning' ? '#F59E0B' : '#22384C';

    if (zone === 'danger') {
      alertBanner.style.display = 'block';
      alertBanner.textContent = 'DANGER \u2014 Object at ' + stats.closestDist.toFixed(1) + 'm';
      document.getElementById('status-dot').className = 'dot dot-red';
    } else {
      alertBanner.style.display = 'none';
      document.getElementById('status-dot').className = 'dot dot-green';
    }
  }

  return {
    update: update
  };
})();
