# Branding & visual language (working notes)

The brand and domain are TBD. These are the working aesthetic principles
the atlas is being built against; revise once a name lands.

## Metaphor

The grid as a **mycelial network** — branching, breathing, mostly invisible
infrastructure that connects life across a continent. Transmission lines are
hyphae; substations are nodes where hyphae braid; generation plants are
fruiting bodies. Trees and root systems are the secondary metaphor, with the
same family of forms.

## Principles

1. **Calm by default.** The base map is muted earth — loam, bone, moss,
   ochre, heartwood. The eye should rest on it, not flinch.
2. **Alarm colors are reserved.** Red and bright green are used **only** for
   scenario overlays (overloads, mitigations). Because they're the only
   saturated colors on the map, they pop against the calm base without
   being visually loud.
3. **Hue, not stridency, encodes data.** Voltage and fuel are distinguished
   by hue family within the earth palette, never by saturation cranked to
   the limit.
4. **Botanical typography.** A serif (system serif by default; revisit
   when we license something appropriate) for chrome and labels — closer
   to a field guide than a dashboard.
5. **Generous whitespace, low contrast borders.** Panels sit *on* the map
   like specimen cards, not floating UI tiles.

## Palette — see `src/theme.ts`

```
loam900   #1c1812   chrome / strokes
loam700   #3b3228   secondary text
loam500   #6b5d4a   borders, baseline hyphae
bone      #f3ede0   panels, popovers
paper     #faf6ec   page background

hypha 115–765 kV   moss → leaf → ochre → rust bark → heartwood
fuel solar/wind/gas/coal/nuclear/hydro/other  fruiting-body hues

overload     #c0392b   reserved for overlays
mitigation   #3aa17a   reserved for overlays
```

## Avoid

- Engineering primaries (the Reds/Greens/Blues of voltage class diagrams).
- Dark-mode-as-default cyber dashboards.
- Geometric sans-serif everywhere.
- Drop shadows, glow effects, animation for its own sake.
