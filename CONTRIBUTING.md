# Contributing

## Branches

- `main` — accepted release history; no direct pushes.
- `develop` — integration branch for the test environment.
- `feat/<short-name>` — product functionality.
- `fix/<short-name>` — defect correction.
- `chore/<short-name>` — tooling or maintenance.
- `docs/<short-name>` — documentation only.

Create a short-lived branch from an up-to-date `develop`. Keep unrelated work
in separate pull requests.

## Commits

Use clear, imperative Conventional Commit messages, for example:

```text
feat(season): add explicit transition validation
fix(purchase): make balance update atomic
docs: describe the release workflow
```

Never commit `.env`, bot tokens, private keys, database dumps, personal data,
media uploads, caches, or generated runtime files.

## Pull requests

Before requesting review:

```sh
python manage.py test --settings=mysite.settings_test
python manage.py check --settings=mysite.settings_test
python manage.py makemigrations --check --dry-run --settings=mysite.settings_test
```

Describe product impact, verification, migrations, deployment implications,
known risks, and rollback. Merge feature and fix pull requests into `develop`
only after required CI checks pass. Promote `develop` to `main` with a release
pull request after staging acceptance by the owner.

Use squash merge for ordinary feature/fix pull requests. Use a merge commit for
the release pull request so the release boundary remains visible.
