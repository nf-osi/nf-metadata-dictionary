"""Guards the assumptions behind in-process JSON Schema generation.

`utils/gen-json-schema-class.py` used to shell out to the `gen-json-schema` CLI once per
class.  It now imports linkml's JsonSchemaGenerator and reuses a single parsed copy of the
merged model across every class, which is where the speedup comes from.  That rests on two
properties of linkml rather than of this repo, so they are asserted here and will fail
loudly on a version bump instead of silently changing every registered schema:

1. the generator does not mutate the SchemaDefinition it is handed, so one parse can serve
   many classes; and
2. the keyword arguments used are equivalent to the CLI flags they replaced
   (`--inline --no-metadata --not-closed`).

These run against `dist/NF.yaml`, so they are skipped when it has not been built.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_YAML = REPO_ROOT / "dist" / "NF.yaml"

pytestmark = pytest.mark.skipif(
    not SCHEMA_YAML.exists(),
    reason="dist/NF.yaml not built; run `make -B` first",
)

# A deliberately mixed sample: a file-based template, an attributes-style portal class,
# a mixin-composed template and an abstract base.  Generating all 63 here would make the
# suite slower than the thing it is guarding.
SAMPLE_CLASSES = [
    "GenomicsAssayTemplate",
    "PortalDataset",
    "BiospecimenTemplate",
]


def _generator(schema, cls_name):
    from linkml.generators.jsonschemagen import JsonSchemaGenerator

    return JsonSchemaGenerator(
        schema, top_class=cls_name, inline=True, metadata=False, not_closed=True
    ).serialize()


@pytest.fixture(scope="module")
def shared_schema():
    from linkml_runtime.utils.schemaview import load_schema_wrap

    return load_schema_wrap(str(SCHEMA_YAML))


@pytest.mark.parametrize("cls_name", SAMPLE_CLASSES)
def test_shared_schema_matches_fresh_parse(shared_schema, cls_name):
    """Reusing one parsed schema gives the same result as parsing per class."""
    from_shared = json.loads(_generator(shared_schema, cls_name))
    from_fresh = json.loads(_generator(str(SCHEMA_YAML), cls_name))
    assert from_shared == from_fresh, (
        f"{cls_name} differs when generated from a reused SchemaDefinition. linkml has "
        "started mutating the schema it is handed; the worker processes in "
        "utils/gen-json-schema-class.py can no longer share one parse."
    )


def test_shared_schema_survives_repeated_use(shared_schema):
    """Cumulative mutation would only show up after several classes have been generated."""
    first = json.loads(_generator(shared_schema, SAMPLE_CLASSES[0]))
    for cls_name in SAMPLE_CLASSES[1:]:
        _generator(shared_schema, cls_name)
    again = json.loads(_generator(shared_schema, SAMPLE_CLASSES[0]))
    assert first == again, (
        f"{SAMPLE_CLASSES[0]} changed after generating other classes from the same "
        "SchemaDefinition, so generation order now affects output."
    )


@pytest.mark.parametrize("cls_name", SAMPLE_CLASSES[:1])
def test_matches_cli_flags(cls_name):
    """The kwargs must stay equivalent to `--inline --no-metadata --not-closed`."""
    import shutil
    import subprocess

    if not shutil.which("gen-json-schema"):
        pytest.skip("gen-json-schema CLI not on PATH")

    completed = subprocess.run(
        ["gen-json-schema", "--top-class", cls_name,
         "--inline", "--no-metadata", "--not-closed", str(SCHEMA_YAML)],
        stdout=subprocess.PIPE, text=True, check=True,
    )
    assert json.loads(completed.stdout) == json.loads(_generator(str(SCHEMA_YAML), cls_name)), (
        f"In-process generation of {cls_name} no longer matches the CLI invocation it "
        "replaced. Check the JsonSchemaGenerator kwargs against the CLI flags."
    )
