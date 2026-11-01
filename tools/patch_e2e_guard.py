#!/usr/bin/env python3
"""Add the upstream-outage safety net to a derived JS repo's tests/e2e/scraper.test.js.

Why not propagate.py: every derived repo's e2e file carries its own constants, so a
whole-file copy would overwrite them. This applies the same five text edits that the
template's own e2e file received, and only where every anchor is present:

  * helper block (isUpstreamOutage + resilient) before the top-level describe
  * ANAF test and full-validation test wrapped in resilient(...)
  * early return when ANAF/CUIFirma search comes back empty

It is idempotent (a file that already has the helper is left alone) and skips files
whose anchors are missing (older e2e variants, flat-layout repos) instead of guessing.

Usage:
    python tools/patch_e2e_guard.py --parent "<folder with the clones>" [--dry-run] [--no-push]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import propagate  # noqa: E402  (reuses ensure_repo / read_dest / commit_and_push)

REL = "tests/e2e/scraper.test.js"
TEMPLATE_E2E = propagate.ROOT / "scraper-js" / REL
COMMIT_MESSAGE = (
    "test(e2e): skip, don't fail, when ANAF/CUIScan/CUIFirma are down\n\n"
    "Propagated from the Brewtality-3-16 template. The ANAF and full-validation e2e tests "
    "failed the whole Tests workflow (and e-mailed the owner) whenever a free third-party "
    "company-data service answered 403/429/5xx, an HTML page, or timed out. Those errors now "
    "skip the assertions with a warning; any other error or a real assertion failure still fails."
)

ANCHORS = [
    "    itIfAnaf('finds the company in ANAF and reads active status', async () => {\n      const results = await anaf.searchCompany(TEST_BRAND);\n",
    "      expect(data.inactive).toBe(false);\n    }, 30000);\n",
    "    itIfApi('runs full validation and reports active status', async () => {\n",
    "      expect(result.cif).toBe(TEST_CIF);\n    }, 30000);\n",
    "describe('E2E: Full Scraping Pipeline', () => {\n",
]


def helper_block() -> str:
    """The helper text, taken verbatim from the template's already-patched e2e file."""
    t = TEMPLATE_E2E.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = t.index("// Upstream-outage safety net.")
    end = t.index("describe('E2E: Full Scraping Pipeline'")
    return t[start:end]


def patch(text: str) -> tuple[str, str]:
    """Return (new_text, status) with status in patched | already | anchors-missing."""
    lf = text.replace("\r\n", "\n")
    if "isUpstreamOutage" in lf:
        return text, "already"
    if any(lf.count(a) != 1 for a in ANCHORS):
        return text, "anchors-missing"
    lf = lf.replace(
        ANCHORS[0],
        "    itIfAnaf('finds the company in ANAF and reads active status', resilient(async () => {\n"
        "      const results = await anaf.searchCompany(TEST_BRAND);\n"
        "      if (results.length === 0) { console.warn('ANAF/CUIFirma search returned nothing - upstream search unavailable, skipping'); return; }\n",
    )
    lf = lf.replace(ANCHORS[1], "      expect(data.inactive).toBe(false);\n    }), 30000);\n")
    lf = lf.replace(
        ANCHORS[2],
        "    itIfApi('runs full validation and reports active status', resilient(async () => {\n",
    )
    lf = lf.replace(ANCHORS[3], "      expect(result.cif).toBe(TEST_CIF);\n    }), 30000);\n")
    lf = lf.replace(ANCHORS[4], helper_block() + ANCHORS[4])
    return (lf.replace("\n", "\r\n") if "\r\n" in text else lf), "patched"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parent", type=pathlib.Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()
    propagate.PARENT = args.parent.resolve()

    fleet = json.loads(propagate.FLEET_JSON.read_text(encoding="utf-8"))["scrapers"]
    targets = [s for s in fleet if s["status"] == "active" and s["language"] == "js" and s.get("layout", "template") == "template"]
    changed, skipped = [], []
    for s in targets:
        print(f"== {s['repo']} ==")
        repo_dir = propagate.ensure_repo(s, args.dry_run)
        current = propagate.read_dest(repo_dir, REL, args.dry_run)
        if current is None:
            print(f"    SKIP {REL}: missing"); skipped.append((s["repo"], "missing")); continue
        new, status = patch(current)
        print(f"    {status.upper():15} {REL}")
        if status != "patched":
            skipped.append((s["repo"], status)); continue
        changed.append(s["repo"])
        if not args.dry_run:
            (repo_dir / REL).write_bytes(new.encode("utf-8"))
            propagate.commit_and_push(repo_dir, [REL], COMMIT_MESSAGE, False, push=not args.no_push)
    print(f"\nWould patch / patched ({len(changed)}): {', '.join(changed) or '-'}")
    print(f"Skipped ({len(skipped)}): {', '.join(f'{n} [{why}]' for n, why in skipped) or '-'}")


if __name__ == "__main__":
    main()
