from pathlib import Path

NOTEBOOK_DIR = Path("notebooks")

REPLACEMENTS = {
    "from oa_common import": "from oa_pipeline.common import",
    "from oa_schema import": "from oa_pipeline.schema import",
    "from oa_policy import": "from oa_pipeline.policy import",
    "from oa_qc_ta_ph import": "from oa_pipeline.qc_ta_ph import",
    "from oa_stage1b import": "from oa_pipeline.stage1b import",
    "from oa_stage2 import": "from oa_pipeline.stage2 import",
    "from oa_stage3 import": "from oa_pipeline.stage3 import",
    "from oa_stage4 import": "from oa_pipeline.stage4 import",

    "import oa_common": "import oa_pipeline.common as oa_common",
    "import oa_schema": "import oa_pipeline.schema as oa_schema",
    "import oa_policy": "import oa_pipeline.policy as oa_policy",
    "import oa_qc_ta_ph": "import oa_pipeline.qc_ta_ph as oa_qc_ta_ph",
    "import oa_stage1b": "import oa_pipeline.stage1b as oa_stage1b",
    "import oa_stage2": "import oa_pipeline.stage2 as oa_stage2",
    "import oa_stage3": "import oa_pipeline.stage3 as oa_stage3",
    "import oa_stage4": "import oa_pipeline.stage4 as oa_stage4",
}

changed_files = []

for path in sorted(NOTEBOOK_DIR.glob("*.ipynb")):
    text = path.read_text(encoding="utf-8")
    new_text = text

    for old, new in REPLACEMENTS.items():
        new_text = new_text.replace(old, new)

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        changed_files.append(path)

if changed_files:
    print("Updated notebooks:")
    for path in changed_files:
        print(f"  {path}")
else:
    print("No old notebook imports found.")