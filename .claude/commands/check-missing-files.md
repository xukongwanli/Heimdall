Scan this repository for missing files, broken references, and gaps that would block implementation of current or future plans.

## What to check

### 1. Import references
- Scan all Python files (`**/*.py`) for `import` and `from ... import` statements. Verify that every referenced local module has a corresponding file on disk.
- Scan all TypeScript/Vue files (`**/*.ts`, `**/*.vue`) for `import ... from '~/...'` and `import ... from '../...'` statements. Verify those paths resolve to real files.

### 2. Config references
- Check `settings.py`, `nuxt.config.ts`, `alembic.ini`, `docker-compose.yml`, `package.json`, and `scrapy.cfg` for file paths or module references. Verify they exist.
- Check pipeline class references in `ITEM_PIPELINES` against actual classes in `pipelines.py`.
- Check `SPIDER_MODULES` and `NEWSPIDER_MODULE` settings resolve to real packages.

### 3. Asset references
- Scan Vue/TypeScript files for `fetch('/geo/...')` or similar static asset references. Verify those files exist under `frontend/public/`.
- Check that GeoJSON files referenced in components are non-empty (> 10 bytes).

### 4. Plan/spec references
- If any `docs/superpowers/specs/*.md` files exist, scan them for file paths mentioned in the plan. Verify each referenced file exists, or flag it as "needs to be created."

### 5. Database references
- Check that every SQLAlchemy model in `backend/app/models.py` has a corresponding Alembic migration that creates its table.
- Check that every table referenced in raw SQL (`text("""...""")`) in pipeline code has a matching model.

### 6. Script references
- Check if any scripts referenced in docs (`docs/*.md`, `README.md`, `CLAUDE.md`) actually exist under `scripts/`.

## Output format

Produce a report grouped by category:

```
## Missing Files Report

### Broken imports
- <file>:<line> imports `<module>` — file not found at <expected_path>

### Missing assets
- <component> references `<asset_path>` — file missing or empty

### Plan gaps (files to create)
- <spec_file> references `<path>` — does not exist yet

### Missing migrations
- Model `<ModelName>` has no migration for table `<table_name>`

### Stale references
- <config_file> references `<path_or_module>` — no longer exists
```

If everything checks out for a category, print "All clear" for that section.
