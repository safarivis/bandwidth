# Bandwidth — design language

The look is **Apple / Jobs**: calm, monochrome, generous space, one clear thing per view. Everything new (onboarding, future screens) must match this. When in doubt: remove, don't add.

## Principles
1. **Clarity over decoration.** Content first; chrome disappears. No gradients, no shadows-for-show, no clutter.
2. **Monochrome + meaning-only colour.** The UI is black/white/grey. Colour appears *only* to carry meaning (health, risk).
3. **One focus per screen.** A view answers one question. Whitespace does the work.
4. **Soft, precise motion.** Small, quick transitions (120–180ms). Never bouncy.
5. **Plain words.** Human language, short. "Needs you", not "Blocked (P1)".

## Palette (CSS variables — light default, dark mirror)
| Token | Light | Dark |
|---|---|---|
| bg | `#ffffff` | `#000000` |
| panel / panel2 | `#ffffff` / `#f5f5f7` | `#1c1c1e` / `#2c2c2e` |
| line (hairline) | `#e5e5e7` | `#38383a` |
| text / dim / dimmer | `#1d1d1f` / `#6e6e73` / `#a1a1a6` | `#f5f5f7` / `#98989d` / `#636366` |
| accent (mono) | `#1d1d1f` (fg `#fff`) | `#ffffff` (fg `#000`) |
| **meaning only →** green / amber / red / grey | `#34c759` / `#ff9f0a` / `#ff3b30` / `#8e8e93` | `#30d158` / `#ffd60a` / `#ff453a` / `#8e8e93` |

Health + risk are the *only* things allowed to use green/amber/red. Priority/criticality use the mono accent (a ★ / ring), never a competing colour.

## Type
- System stack: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif`.
- Antialiased; tight tracking (`letter-spacing:-0.01em`); headings `-0.02em`, weight 600.
- Sizes: body 14, meta/caption 11–12, H1 17.

## Components
- **Buttons:** pill (`border-radius:980px`), 1px line, `.primary` = accent bg + accent-fg. Hover = subtle bg shift.
- **Cards / rows:** `border-radius:12px`, hairline border, soft shadow, 3px health stripe on the left; hover lifts 1px.
- **Inputs / selects:** panel2 bg, hairline border, `border-radius:8–980px`, focus = accent border.
- **Segmented toggle** (views), **icon buttons** (34px circle) for theme/search/risk.
- **Tags:** pill, 10px, 700 weight. `★ Priority` = mono accent; `🔥 At risk` = red; criticality chip = quiet grey.

## Tone of copy
Warm, direct, brief. Lead with the point. A busy person reads it in one glance. No jargon, no exclamation spam.

## Rule
Any new surface (onboarding, settings, client screens) reuses these tokens + components. If something needs a new colour or a heavier element, that's a signal to simplify instead.
