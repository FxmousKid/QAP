# QAP

The rules that must survive a change, and the test that proves each one, are in [docs/map.md](docs/map.md).

After editing a file, run the command that map names for it. The whole suite is:

```bash
uv run --project . python -m unittest discover -s tests
```
