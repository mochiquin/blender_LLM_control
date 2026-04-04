# GenScene — AI-Driven Scene Building Tool for Blender

Describe a scene in plain language and watch it build itself.

---

## Installation

1. Zip the `genscene/` folder:
   ```bash
   cd blender_LLM_control
   zip -r genscene.zip genscene/
   ```
2. In Blender: **Edit → Preferences → Add-ons → Install** → select `genscene.zip`.
3. Enable the add-on by ticking the checkbox next to **"GenScene"**.

No `pip install` required — the add-on uses only Python's stdlib `urllib`.

---

## Configuration

Open `genscene/config.py` and set:

| Variable | Description |
|---|---|
| `API_KEY` | Your OpenAI or Anthropic API key (or set `GENSCENE_API_KEY` env var) |
| `API_PROVIDER` | `"openai"` or `"anthropic"` |
| `ASSET_LIBRARY_PATH` | Absolute path to the root folder containing your `.blend` assets |

---

## Usage

1. Open the **Sidebar** (press `N`) in the 3D Viewport.
2. Click the **GenScene** tab.
3. Type a natural-language prompt, e.g.:
   - *"Place five barrels in a circle around the origin"*
   - *"Scatter debris along the road curve"*
   - *"Stack three crates at (2, 0, 0) and let them fall"*
4. Choose a **Style** preset (optional).
5. Click **Generate**.

All generated objects are wrapped in a single undo group — one **Ctrl+Z** removes everything the AI created.

---

## Project Structure

```
genscene/
├── __init__.py              Blender add-on entry point
├── config.py                API keys, model, physics settings
├── lib/
│   ├── ground.py            get_ground_z() — ray-cast surface detection
│   ├── spawn.py             spawn_asset(), place_on_ground()
│   ├── physics.py           apply_physics_drop() — frame-step simulation
│   └── scene_serializer.py  serialize_scene() — scene → JSON with bbox
├── ai/
│   ├── api_client.py        urllib LLM client (OpenAI + Anthropic)
│   ├── prompt_builder.py    System prompt + scene JSON injection
│   ├── code_extractor.py    Clean + exec() AI code with retry loop
│   └── asset_index.py       Keyword search over local .blend library
├── ui/
│   ├── panel.py             N-panel sidebar (VIEW3D_PT_GenScene)
│   └── operators.py         Generate / Refresh / Copy JSON operators
└── brushes/
    ├── style_presets.py     Post-Apocalyptic, Clean Interior, etc.
    └── distribute.py        distribute_along_curve(), scatter_cluster()
```

---

## Phase Roadmap

| Phase | Description | Status |
|---|---|---|
| 1 | Atomic function library (`lib/`) | Complete |
| 2 | AI brain — API + prompt + exec | Complete |
| 3 | Scene awareness — JSON + bbox | Complete |
| 4 | Blender UI (N-panel) | Complete |
| 5 | Style presets + distribution brushes | Complete |

---

## Pressure Tests

Run these to validate the full pipeline:

- **Semantic scatter**: *"Randomly knock over 5 barrels around the big table"* → AI reads `table.bbox` from scene JSON, computes spread, emits correct `spawn_asset` + `apply_physics_drop` calls.
- **Physics stack**: *"Stack 3 containers vertically at (0,0,10)"* → frame-step physics produces natural collision without mesh overlap.
- **Fuzzy asset lookup**: *"Put something rusty there"* → `AssetIndex.find()` keyword match returns `rust_bucket.blend`.
