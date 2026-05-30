# data/

Working data folders. Tracked structure, ignored contents (see `.gitignore`).

- `raw/` — original, immutable input workbooks. Never edit in place.
- `interim/` — intermediate transformed data.
- `processed/` — final canonical datasets.
- `external/` — third-party reference data (e.g. CRM certificates).

The bundled synthetic example lives in `examples/`, not here. Real input
workbooks may live in OneDrive; keep the project folder itself outside OneDrive
(see the README note).
