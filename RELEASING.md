# Releasing PySynthea to PyPI

The package is published to **PyPI as [`py-synthea`](https://pypi.org/project/py-synthea/)**
by GitHub Actions using **Trusted Publishing (OIDC)** — no API tokens or secrets
are stored anywhere. A publish is triggered by **publishing a GitHub Release**.

Workflow: [`.github/workflows/publish.yml`](.github/workflows/publish.yml).

---

## One-time setup (do this once, before the first release)

### 1. Register the Trusted Publisher on PyPI

Because `py-synthea` does not exist on PyPI yet, use the **pending publisher**
flow:

1. Log in to PyPI and open <https://pypi.org/manage/account/publishing/>.
2. Under **"Add a new pending publisher"**, enter exactly:
   | Field | Value |
   |-------|-------|
   | PyPI Project Name | `py-synthea` |
   | Owner | `TIET-AI` |
   | Repository name | `tietai-synthea` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |
3. Click **Add**. PyPI will now trust releases published by this repo's
   `publish.yml` running in the `pypi` environment. The project is created
   automatically on the first successful publish.

> The account that registers the pending publisher becomes the initial owner of
> the `py-synthea` project on PyPI.

### 2. Create the `pypi` GitHub Environment

1. In GitHub: **Settings → Environments → New environment**, name it `pypi`.
2. (Recommended) Add yourself as a **required reviewer** so every publish waits
   for a manual approval click — a safety gate for the irreversible upload.

---

## Cutting a release

1. **Set the version.** Update it in **both** files so they match:
   - `pyproject.toml` → `[project] version = "X.Y.Z"`
   - `src/synthea/__init__.py` → `__version__ = "X.Y.Z"`

   (The publish workflow refuses to run if the release tag doesn't match the
   `pyproject.toml` version.)

2. **Merge to `main` via PR** with CI green (`.github/workflows/ci.yml` runs the
   test matrix, lint, and a build/verify job).

3. **Publish a GitHub Release:**
   - Tag: `vX.Y.Z` (e.g. `v1.0.0`) — the `v` prefix is stripped when compared
     to the package version.
   - Target: `main`.
   - Add release notes, then **Publish release**.

4. The **Publish to PyPI** workflow runs automatically:
   - `build` — verifies the tag matches the version, builds the sdist + wheel,
     runs `twine check`.
   - `pypi-publish` — (waits for approval if you enabled it) uploads to PyPI via
     OIDC.

5. **Verify:**
   ```bash
   pip install py-synthea==X.Y.Z
   synthea --version
   ```
   and check <https://pypi.org/project/py-synthea/>.

---

## Notes

- **Versions are permanent.** PyPI never allows re-uploading the same version.
  To fix a broken release, bump the version (e.g. `1.0.1`) and release again;
  you can `yank` a bad version but not replace it.
- **TestPyPI (optional).** To rehearse without touching real PyPI, register a
  second pending publisher on <https://test.pypi.org> with the same values, add
  a `with: repository-url: https://test.pypi.org/legacy/` step to a copy of the
  publish job, and install with
  `pip install --index-url https://test.pypi.org/simple/ py-synthea`.
- The import name and console command remain `synthea`; only the PyPI
  distribution name is `py-synthea`.
