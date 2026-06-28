// LilyGo T4-S3 — 2.41" AMOLED RM690B0 (QSPI)
// Source: github.com/Xinyuan-LilyGO/LilyGo-AMOLED-Series — RM690B0_AMOLED config
#pragma once

#define LCD_SDIO0 14
#define LCD_SDIO1 10
#define LCD_SDIO2 16
#define LCD_SDIO3 12
#define LCD_SCLK  15
#define LCD_CS    11
#define LCD_RST   13
#define LCD_TE    18
#define LCD_POWER 9    // T4-S3 gates panel VCC through this pin — must be HIGH

// Panel visible area. Native is 482x600 but the module exposes 450x600.
#define LCD_WIDTH  450
#define LCD_HEIGHT 600

// QSPI timing (T4-S3 spec: 36 MHz max for reliable operation).
#define LCD_FREQ   36000000
