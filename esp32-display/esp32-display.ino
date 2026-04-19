// GridFront Detect — ESP32-S3 cab display firmware
// Target: LilyGo T4-S3 (2.41" AMOLED, RM690B0 QSPI, ESP32-S3R8 + 8MB PSRAM)
// Receives detection UDP from the Detect Flask server and renders a radar view.

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// Must precede Arduino_GFX_Library — LilyGo's T4-S3 rates the QSPI link at 36 MHz.
#define ESP32QSPI_FREQUENCY 36000000
#include <Arduino_GFX_Library.h>

// Adafruit-style GFX proportional fonts. These ship as plain progmem C
// arrays so the linker drops any face we don't actually use.
#include "FreeSans9pt7b.h"
#include "FreeSansBold18pt7b.h"
#include "FreeSansBold24pt7b.h"

#include "pin_config.h"
#include "secrets.h"

// ── Display ────────────────────────────────────────────────────
Arduino_DataBus *bus = new Arduino_ESP32QSPI(
    LCD_CS, LCD_SCLK, LCD_SDIO0, LCD_SDIO1, LCD_SDIO2, LCD_SDIO3);

// T4-S3 uses the RM690B0 (2.41" 450x600 visible on a 482x600 native panel).
// The 16px column offset centers the visible area in the controller's RAM window.
Arduino_GFX *panel = new Arduino_RM690B0(
    bus, LCD_RST, 0 /*rotation*/,
    LCD_WIDTH, LCD_HEIGHT,
    16 /*col_offset1*/, 0 /*row_offset1*/, 16 /*col_offset2*/, 0 /*row_offset2*/);

// Full-screen 16-bit canvas in PSRAM. ~540 KB — fits comfortably in 8 MB.
Arduino_Canvas *gfx = new Arduino_Canvas(LCD_WIDTH, LCD_HEIGHT, panel);

// ── Radar geometry ─────────────────────────────────────────────
// Full-bleed radar, machine dead-centered so forward (+z) is up and the
// operator sees bearing in all directions at a glance. 30 px per metre —
// keeps the 3m and 6m rings prominent, 9m/12m partially clipped at corners.
static const int16_t MCX         = LCD_WIDTH / 2;          // 225
static const int16_t MCY         = LCD_HEIGHT / 2;         // 300
static const float   PX_PER_M    = 30.0f;
static const int16_t PILL_Y      = LCD_HEIGHT - 60;        // bottom status pill center

// Brand palette (RGB565 from the GridFront logo). Used on splash + safe-state.
static const uint16_t C_BRAND_D    = 0x3B33;   // dark slate blue column
static const uint16_t C_BRAND_M    = 0x357A;   // cyan column / safe accent
static const uint16_t C_BRAND_L    = 0x9E9C;   // light sky column
static const uint16_t C_BRAND_NAVY = 0x21A9;   // wordmark slate

// UI neutrals (clear / safe state).
static const uint16_t C_BG_SAFE    = 0x0000;   // AMOLED black
static const uint16_t C_GRID       = 0x10A2;   // subtle ring on black
static const uint16_t C_GRID_HI    = 0x2124;   // prominent ring on black
static const uint16_t C_TEXT       = 0xFFFF;   // primary text
static const uint16_t C_TEXT_DIM   = 0x8C71;   // muted label text
static const uint16_t C_PILL_BG    = 0x18E3;   // resting pill (on black)

// Zone palette — matches the webview exactly so the cab display reads
// the same colour as the operator's tablet in every state.
//   Bright: #ef4444 / #f59e0b  (Tailwind red-500 / amber-500) — accents.
//   Deep:   #b91c1c / #b45309  (Tailwind red-700 / amber-700) — full bg.
// The deeper shade as the wash means white rings/text/glyphs still read
// against it, while still being unmistakably red or yellow at a glance.
static const uint16_t C_SAFE         = 0x357A;   // brand cyan accent
static const uint16_t C_WARN         = 0xF4E1;   // #f59e0b
static const uint16_t C_DANGER       = 0xEA28;   // #ef4444
static const uint16_t C_BG_DANGER    = 0xB8E3;   // #b91c1c full-bg wash
static const uint16_t C_BG_WARN      = 0xB281;   // #b45309 full-bg wash
static const uint16_t C_RING_ON_WASH = 0xFFFF;   // white rings on coloured bg

// Machine glyph (on black). On alarm bg we draw a brighter outline variant.
static const uint16_t C_MACHINE      = 0x2104;   // dark chassis
static const uint16_t C_MACHINE_HI   = 0x4A69;   // outline on black

// ── Detection state ────────────────────────────────────────────
struct Dot {
  int32_t  track_id;
  float    x_m, z_m;         // machine-frame metres
  float    distance_m;
  uint8_t  zone;             // 0 safe, 1 warn, 2 danger
  uint32_t last_seen_ms;
  bool     active;
};

static const uint8_t MAX_DOTS = 24;
static const uint32_t DOT_TTL_MS = 1500;
static Dot dots[MAX_DOTS];

// Global zone flags + nearest-distance, from the server's summary block.
static bool  any_danger  = false;
static bool  any_warning = false;
static float closest_m   = -1.0f;   // <0 ⇒ no detections to report

// Operator-facing unit — shadowed from each broadcast. Default 'm' until
// the first packet arrives so labels remain readable on boot.
static char display_units[4] = "m";

// Link health. The broadcaster sends "link":"stale" when the camera
// pipeline hasn't produced a frame in a few seconds. Even when no UDP
// arrives at all (server offline) we still flip to stale after a timeout
// — operators must never see a frozen detection on a safety display.
static bool     link_ok           = false;
static uint32_t last_packet_ms    = 0;
static const uint32_t LINK_TIMEOUT_MS = 5000;

// ── Networking ─────────────────────────────────────────────────
static WiFiUDP  udp;
static uint32_t last_register_ms = 0;
static const uint32_t REGISTER_INTERVAL_MS = 15000;  // heartbeat to server

// Format a metre value using the operator-facing unit. Mirrors the
// webview's formatDist(): decimal precision under 8 m, whole units beyond,
// so the label doesn't imply precision the stereo baseline can't back up.
static void format_distance(float m, char *out, size_t out_len) {
  bool ft = (display_units[0] == 'f');
  if (ft) {
    float v = m * 3.28084f;
    if (m < 8.0f) snprintf(out, out_len, "%.1fft", v);
    else          snprintf(out, out_len, "%dft", (int)(v + 0.5f));
  } else {
    if (m < 8.0f) snprintf(out, out_len, "%.1fm", m);
    else          snprintf(out, out_len, "%dm", (int)(m + 0.5f));
  }
}

// Per-channel RGB565 lerp. Used strictly for static halo composition now
// that the background itself doesn't pulse — no time-varying blends.
static uint16_t blend565(uint16_t a, uint16_t b, float t) {
  if (t < 0) t = 0; else if (t > 1) t = 1;
  uint16_t ar = (a >> 11) & 0x1F, ag = (a >> 5) & 0x3F, ab = a & 0x1F;
  uint16_t br = (b >> 11) & 0x1F, bg = (b >> 5) & 0x3F, bb = b & 0x1F;
  uint16_t r = ar + (uint16_t)((int16_t)(br - ar) * t);
  uint16_t g = ag + (uint16_t)((int16_t)(bg - ag) * t);
  uint16_t bl = ab + (uint16_t)((int16_t)(bb - ab) * t);
  return (r << 11) | (g << 5) | bl;
}

// The brand mark: 3x3 grid of rounded tiles, three columns of blue shades.
// Scales cleanly from a hero splash down to a 24 px HUD glyph.
static void draw_logo(int16_t cx, int16_t cy, int16_t tile, int16_t gap) {
  const uint16_t cols[3] = {C_BRAND_D, C_BRAND_M, C_BRAND_L};
  int16_t total = 3 * tile + 2 * gap;
  int16_t x0 = cx - total / 2;
  int16_t y0 = cy - total / 2;
  int16_t r  = tile / 4; if (r < 1) r = 1;
  for (uint8_t col = 0; col < 3; col++) {
    for (uint8_t row = 0; row < 3; row++) {
      int16_t x = x0 + col * (tile + gap);
      int16_t y = y0 + row * (tile + gap);
      gfx->fillRoundRect(x, y, tile, tile, r, cols[col]);
    }
  }
}

// Machine silhouette — a compact top-down chassis with a brand-blue forward
// chevron. On alarm bg we invert the chassis to white so it stands out
// against red/amber instead of disappearing into it.
static void draw_machine_glyph(int16_t cx, int16_t cy, uint16_t bg) {
  bool on_alarm = (bg != C_BG_SAFE);
  uint16_t chassis = on_alarm ? C_TEXT          : C_MACHINE;
  uint16_t outline = on_alarm ? C_TEXT          : C_MACHINE_HI;
  uint16_t window  = on_alarm ? bg              : C_BG_SAFE;
  uint16_t chevron = on_alarm ? C_BRAND_NAVY    : C_BRAND_M;
  gfx->fillRoundRect(cx - 12, cy - 18, 24, 36, 3, chassis);
  gfx->drawRoundRect(cx - 12, cy - 18, 24, 36, 3, outline);
  gfx->fillRoundRect(cx - 8,  cy - 12, 16, 12, 2, window);
  gfx->fillTriangle(cx, cy - 24, cx - 5, cy - 18, cx + 5, cy - 18, chevron);
}

static void draw_range_rings(uint16_t bg) {
  // Concentric scale rings at 3 / 6 / 9 / 12 m. Colours flip based on the
  // background — translucent white on coloured washes, near-black on safe.
  const float ring_m[] = {3.0f, 6.0f, 9.0f, 12.0f};
  if (bg == C_BG_SAFE) {
    const uint16_t base[4] = {C_GRID_HI, C_GRID_HI, C_GRID, C_GRID};
    for (uint8_t i = 0; i < 4; i++) {
      gfx->drawCircle(MCX, MCY, (int16_t)(ring_m[i] * PX_PER_M), base[i]);
    }
  } else {
    // White rings, slightly faded into the wash so they read as scale not
    // chrome. The 3 m and 6 m rings are emphasised because they're the
    // ones the alarm thresholds pivot on.
    uint16_t prom = blend565(bg, C_RING_ON_WASH, 0.85f);
    uint16_t soft = blend565(bg, C_RING_ON_WASH, 0.55f);
    const uint16_t base[4] = {prom, prom, soft, soft};
    for (uint8_t i = 0; i < 4; i++) {
      gfx->drawCircle(MCX, MCY, (int16_t)(ring_m[i] * PX_PER_M), base[i]);
    }
  }
}

static void draw_status_pill(uint16_t bg) {
  // Bottom-center pill: zone indicator dot + label + nearest distance. This
  // IS the cab HUD — one glance, one decision.
  uint16_t accent = any_danger  ? C_DANGER
                  : any_warning ? C_WARN
                  :               C_SAFE;
  const char *zlabel = any_danger  ? "DANGER"
                     : any_warning ? "WARNING"
                     :               "CLEAR";
  char dbuf[16];
  if (closest_m >= 0) format_distance(closest_m, dbuf, sizeof(dbuf));
  else                snprintf(dbuf, sizeof(dbuf), "--");

  // Pill colours flip on alarm bg: white pill body so dark coloured text
  // pops against the wash. On safe (black) bg the pill stays dark with
  // light text.
  bool on_alarm = (bg != C_BG_SAFE);
  uint16_t pill_bg     = on_alarm ? C_TEXT       : C_PILL_BG;
  uint16_t pill_border = on_alarm ? accent       : blend565(C_PILL_BG, accent, 0.55f);
  uint16_t label_color = on_alarm ? C_BRAND_NAVY : C_TEXT;
  uint16_t sep_color   = on_alarm ? blend565(pill_bg, C_BRAND_NAVY, 0.4f) : C_TEXT_DIM;

  // Measure label + distance in their fonts so we can size the pill tightly.
  gfx->setFont(&FreeSansBold18pt7b);
  int16_t tx, ty; uint16_t lw, lh, dw, dh;
  gfx->getTextBounds(zlabel, 0, 0, &tx, &ty, &lw, &lh);
  gfx->getTextBounds(dbuf,   0, 0, &tx, &ty, &dw, &dh);

  const int16_t pad_x     = 22;
  const int16_t gap       = 18;
  const int16_t sep_w     = 10;
  const int16_t dot_r     = 8;
  const int16_t dot_gap   = 12;
  int16_t inner = dot_r * 2 + dot_gap + lw + gap + sep_w + gap + dw;
  int16_t pill_w = inner + pad_x * 2;
  int16_t pill_h = 52;
  int16_t px = (LCD_WIDTH - pill_w) / 2;
  int16_t py = PILL_Y - pill_h / 2;

  gfx->fillRoundRect(px, py, pill_w, pill_h, pill_h / 2, pill_bg);
  gfx->drawRoundRect(px, py, pill_w, pill_h, pill_h / 2, pill_border);

  int16_t cx = px + pad_x;
  int16_t cy = py + pill_h / 2;

  gfx->fillCircle(cx + dot_r, cy, dot_r + 3, blend565(pill_bg, accent, 0.35f));
  gfx->fillCircle(cx + dot_r, cy, dot_r, accent);
  cx += dot_r * 2 + dot_gap;

  gfx->setTextColor(label_color);
  gfx->setCursor(cx, cy + lh / 2 - 2);
  gfx->print(zlabel);
  cx += lw + gap;

  gfx->fillCircle(cx + sep_w / 2, cy, 2, sep_color);
  cx += sep_w + gap;

  gfx->setTextColor(on_alarm ? accent : accent);
  gfx->setCursor(cx, cy + dh / 2 - 2);
  gfx->print(dbuf);
}

static void draw_dot(const Dot &d, uint16_t bg) {
  // Project machine-frame (x,z) → screen, forward = up.
  int16_t sx = MCX + (int16_t)(d.x_m * PX_PER_M);
  int16_t sy = MCY - (int16_t)(d.z_m * PX_PER_M);
  const int16_t margin = 18;
  if (sx < margin)                 sx = margin;
  if (sx > LCD_WIDTH  - margin)    sx = LCD_WIDTH  - margin;
  if (sy < margin + 8)             sy = margin + 8;
  if (sy > PILL_Y - 60)            sy = PILL_Y - 60;

  uint16_t tint = (d.zone == 2) ? C_DANGER
                : (d.zone == 1) ? C_WARN
                :                 C_SAFE;

  // 5-layer soft glow — outer rings blend into the current bg, inner core
  // brightens toward white. Blending against the actual bg means the glow
  // edges match the wash and don't show a halo seam.
  gfx->fillCircle(sx, sy, 22, blend565(bg,    tint,   0.18f));
  gfx->fillCircle(sx, sy, 17, blend565(bg,    tint,   0.45f));
  gfx->fillCircle(sx, sy, 12, tint);
  gfx->fillCircle(sx, sy,  8, blend565(tint,  C_TEXT, 0.55f));
  gfx->fillCircle(sx, sy,  4, C_TEXT);

  // Small per-dot distance tag — white on safe bg, navy on alarm bg so it
  // reads against the white-cored glow regardless of background.
  char buf[12];
  format_distance(d.distance_m, buf, sizeof(buf));
  gfx->setFont(&FreeSans9pt7b);
  gfx->setTextColor(C_TEXT);
  int16_t tx, ty; uint16_t tw, th;
  gfx->getTextBounds(buf, 0, 0, &tx, &ty, &tw, &th);
  int16_t ly = sy - 28;
  if (ly < margin + 16) ly = sy + 34;
  gfx->setCursor(sx - tw / 2, ly);
  gfx->print(buf);
}

// Boot splash: hero logo + wordmark. Held for ~1.5s before we fade to the
// live UI so the brand reads even if the WiFi handshake is fast.
static void draw_brand_splash() {
  gfx->fillScreen(C_BG_SAFE);
  // Hero logo, centered high on the canvas.
  draw_logo(MCX, MCY - 40, 44, 10);
  // Wordmark in the big bold face, then a lighter subhead.
  gfx->setFont(&FreeSansBold24pt7b);
  gfx->setTextColor(C_TEXT);
  int16_t tx, ty; uint16_t tw, th;
  gfx->getTextBounds("GridFront", 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, MCY + 80);
  gfx->print("GridFront");
  gfx->setFont(&FreeSans9pt7b);
  gfx->setTextColor(C_TEXT_DIM);
  gfx->getTextBounds("Detect", 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, MCY + 110);
  gfx->print("Detect");
  gfx->flush();
}

// Transitional splash while we wait for network. Same layout as brand
// splash but swaps the subhead for a live status string.
static void draw_status_splash(const char *msg) {
  gfx->fillScreen(C_BG_SAFE);
  draw_logo(MCX, MCY - 40, 44, 10);
  gfx->setFont(&FreeSansBold24pt7b);
  gfx->setTextColor(C_TEXT);
  int16_t tx, ty; uint16_t tw, th;
  gfx->getTextBounds("GridFront", 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, MCY + 80);
  gfx->print("GridFront");
  gfx->setFont(&FreeSans9pt7b);
  gfx->setTextColor(C_TEXT_DIM);
  gfx->getTextBounds(msg, 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, MCY + 110);
  gfx->print(msg);
  gfx->flush();
}

// Production offline screen. Used whenever the broadcaster says the link
// is stale, OR we've heard no UDP for LINK_TIMEOUT_MS. Brand-forward,
// no panic colours, and a clear next step (email support) so operators
// in the cab know exactly what to do.
static void draw_offline_screen() {
  gfx->fillScreen(C_BG_SAFE);

  // GridFront mark, top-third. Same hero style as the boot splash.
  draw_logo(MCX, MCY - 140, 22, 6);
  gfx->setFont(&FreeSansBold18pt7b);
  gfx->setTextColor(C_TEXT);
  int16_t tx, ty; uint16_t tw, th;
  gfx->getTextBounds("GridFront", 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, MCY - 60);
  gfx->print("GridFront");

  // Title — amber so it reads as "system attention", not danger red.
  gfx->setFont(&FreeSansBold24pt7b);
  gfx->setTextColor(C_WARN);
  gfx->getTextBounds("CAMERA OFFLINE", 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, MCY + 0);
  gfx->print("CAMERA OFFLINE");

  // Body — short, plain, one idea per line. 9pt face is the readable
  // limit at viewing distance from a cab seat.
  gfx->setFont(&FreeSans9pt7b);
  gfx->setTextColor(C_TEXT);
  const char *lines[] = {
    "The detection system has lost",
    "contact with the camera.",
    "",
    "Operate with caution and",
    "report this to support.",
  };
  int16_t y = MCY + 50;
  for (uint8_t i = 0; i < sizeof(lines) / sizeof(lines[0]); i++) {
    gfx->getTextBounds(lines[i], 0, 0, &tx, &ty, &tw, &th);
    gfx->setCursor((LCD_WIDTH - tw) / 2, y);
    gfx->print(lines[i]);
    y += 22;
  }

  // Support contact, accent-coloured so the eye catches it last.
  gfx->setFont(&FreeSansBold18pt7b);
  gfx->setTextColor(C_BRAND_M);
  const char *email = "support@gridfront.io";
  gfx->getTextBounds(email, 0, 0, &tx, &ty, &tw, &th);
  gfx->setCursor((LCD_WIDTH - tw) / 2, LCD_HEIGHT - 40);
  gfx->print(email);

  gfx->flush();
}

static void render_frame() {
  if (!link_ok) {
    draw_offline_screen();
    return;
  }
  // Background is the alarm signal — full red on danger, full amber on
  // warning, AMOLED black when clear. Matches the webview's cab-bg-disc
  // palette so tablet and cab display read the same colour at a glance.
  uint16_t bg = any_danger  ? C_BG_DANGER
              : any_warning ? C_BG_WARN
              :               C_BG_SAFE;
  gfx->fillScreen(bg);
  draw_range_rings(bg);
  draw_machine_glyph(MCX, MCY, bg);
  for (uint8_t i = 0; i < MAX_DOTS; i++) {
    if (dots[i].active) draw_dot(dots[i], bg);
  }
  // CLEAR state stays visually quiet — rings + machine only. The status
  // pill appears the moment something enters a warning or danger zone, so
  // its presence is itself a signal the operator should look.
  if (any_danger || any_warning) {
    draw_status_pill(bg);
  }
  gfx->flush();
}

static int8_t find_dot_slot(int32_t track_id) {
  int8_t free_slot = -1;
  for (uint8_t i = 0; i < MAX_DOTS; i++) {
    if (dots[i].active && dots[i].track_id == track_id) return i;
    if (!dots[i].active && free_slot == -1) free_slot = i;
  }
  return free_slot;
}

static uint8_t parse_zone(const char *z) {
  if (!z) return 0;
  if (strcmp(z, "DANGER")  == 0) return 2;
  if (strcmp(z, "WARNING") == 0) return 1;
  return 0;
}

static void ingest_packet(const char *json, size_t len) {
  // Payload shape (matches Flask /api/spatial state):
  // { "detections": [{ "track_id", "x_m", "z_m", "distance_m", "zone" }, ...],
  //   "summary":    { "danger_count", "warning_count", ... } }
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, json, len);
  if (err) { Serial.printf("json err: %s\n", err.c_str()); return; }

  JsonArray det = doc["detections"].as<JsonArray>();
  uint32_t now = millis();
  bool seen[MAX_DOTS] = {false};
  for (JsonObject o : det) {
    int32_t tid = o["track_id"] | -1;
    if (tid < 0) continue;   // skip untracked for now — tracker assigns stable IDs
    int8_t slot = find_dot_slot(tid);
    if (slot < 0) continue;   // too many simultaneous tracks, drop oldest would be nicer
    Dot &d = dots[slot];
    d.track_id     = tid;
    d.x_m          = o["x_m"]        | 0.0f;
    d.z_m          = o["z_m"]        | 0.0f;
    d.distance_m   = o["distance_m"] | sqrtf(d.x_m * d.x_m + d.z_m * d.z_m);
    d.zone         = parse_zone(o["zone"] | (const char*)nullptr);
    d.last_seen_ms = now;
    d.active       = true;
    seen[slot]     = true;
  }
  // TTL out stale tracks.
  for (uint8_t i = 0; i < MAX_DOTS; i++) {
    if (!dots[i].active) continue;
    if (!seen[i] && (now - dots[i].last_seen_ms) > DOT_TTL_MS) {
      dots[i].active = false;
    }
  }
  any_danger  = (doc["summary"]["danger_count"]  | 0) > 0;
  any_warning = (doc["summary"]["warning_count"] | 0) > 0;
  // ArduinoJson's default-value operator returns the fallback when the key
  // is missing OR null, which is exactly when we want to show "--".
  closest_m = doc["summary"]["closest_m"] | -1.0f;

  // Link health rides on every packet. Anything other than "ok" — or the
  // field missing — flips us to the offline screen. Older server builds
  // that don't send the field default to stale, which is the safe choice.
  const char *lk = doc["link"] | (const char *)nullptr;
  link_ok = (lk && strcmp(lk, "ok") == 0);

  // Units preference rides on every broadcast; copy in if valid.
  const char *u = doc["units"] | (const char *)nullptr;
  if (u && (strcmp(u, "m") == 0 || strcmp(u, "ft") == 0)) {
    strncpy(display_units, u, sizeof(display_units) - 1);
    display_units[sizeof(display_units) - 1] = '\0';
  }
}

static void register_with_server() {
  HTTPClient http;
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/api/register-display", SERVER_HOST, SERVER_PORT);
  if (!http.begin(url)) return;
  http.addHeader("Content-Type", "application/json");
  char body[96];
  snprintf(body, sizeof(body), "{\"ip\":\"%s\",\"port\":%u}",
           WiFi.localIP().toString().c_str(), UDP_PORT);
  int code = http.POST((uint8_t*)body, strlen(body));
  Serial.printf("register -> %d\n", code);
  // Response echoes the server's current units pref so the very first
  // frame we render already matches what the operator has selected.
  if (code == 200) {
    String body_out = http.getString();
    JsonDocument doc;
    if (!deserializeJson(doc, body_out)) {
      const char *u = doc["units"] | (const char *)nullptr;
      if (u && (strcmp(u, "m") == 0 || strcmp(u, "ft") == 0)) {
        strncpy(display_units, u, sizeof(display_units) - 1);
        display_units[sizeof(display_units) - 1] = '\0';
      }
    }
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[gf-display] boot");

  // Enable panel power rail before any SPI traffic — panel is dark otherwise.
  pinMode(LCD_POWER, OUTPUT);
  digitalWrite(LCD_POWER, HIGH);

  // Arduino_Canvas::begin() initializes the underlying panel + bus for us.
  // Calling panel->begin() separately would double-init the SPI host.
  if (!gfx->begin(LCD_FREQ)) Serial.println("canvas begin failed (check PSRAM config)");

  // Hero brand splash first, then transition to status while WiFi comes up.
  draw_brand_splash();
  delay(1200);
  draw_status_splash("connecting...");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);        // keep radio awake — we need low-latency UDP
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("ip: "); Serial.println(WiFi.localIP());
    draw_status_splash("waiting for data...");
  } else {
    Serial.println("wifi timeout — will retry in loop");
    draw_status_splash("no network");
  }

  udp.begin(UDP_PORT);
  register_with_server();
  last_register_ms = millis();

  // Don't render the live UI until the first packet — without one, link is
  // stale by definition and we'd flash the offline screen on boot. The
  // splash holds until ingest_packet() flips link_ok and loop() repaints.
}

void loop() {
  // Drain any pending UDP packets (newest wins — frames are independent).
  static char pkt_buf[2048];
  int pkt = udp.parsePacket();
  bool got_packet = false;
  while (pkt > 0) {
    int n = udp.read(pkt_buf, sizeof(pkt_buf) - 1);
    if (n > 0) { pkt_buf[n] = '\0'; ingest_packet(pkt_buf, n); got_packet = true; }
    pkt = udp.parsePacket();
  }
  uint32_t now = millis();
  static uint32_t last_idle_paint = 0;

  if (got_packet) last_packet_ms = now;

  // If the broadcaster has gone silent (server crash, WiFi drop) we have
  // to flip to offline ourselves — no packet means no fresh `link`. Treat
  // total silence past LINK_TIMEOUT_MS the same as link:"stale".
  bool prior_link = link_ok;
  if (last_packet_ms == 0 || (now - last_packet_ms) > LINK_TIMEOUT_MS) {
    link_ok = false;
  }
  bool link_changed = (link_ok != prior_link);

  // Age out stale tracks whether a UDP arrived this tick or not. If a track
  // expires the screen needs a redraw so the dot disappears, even with no
  // new packet — flag it so the render gate below picks it up.
  bool ttl_changed = false;
  if (now - last_idle_paint > 250) {
    for (uint8_t i = 0; i < MAX_DOTS; i++) {
      if (dots[i].active && (now - dots[i].last_seen_ms) > DOT_TTL_MS) {
        dots[i].active = false;
        ttl_changed = true;
      }
    }
    last_idle_paint = now;
  }

  // Static UI: render only when state actually changes — on a UDP arrival,
  // when a track ages out, or when the link health flips. No animation
  // floor — the cab UI is dead-still by design.
  if (got_packet || ttl_changed || link_changed) {
    render_frame();
  }

  if (now - last_register_ms > REGISTER_INTERVAL_MS) {
    if (WiFi.status() == WL_CONNECTED) register_with_server();
    else                                WiFi.reconnect();
    last_register_ms = now;
  }
}
