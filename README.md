# Exa Board Finder

Search Exa for companies and check each result for a public Greenhouse, Lever, or Ashby job board. The script uses only Python's standard library.

Set `EXA_API_KEY` in your shell, or add `EXA_API_KEY=your-key` to `~/.config/exa/env`. Then run:

```sh
python3 board_finder.py "AI infrastructure companies" --n 25
```

Use `--known PATH` to compare results with a different known-board list. New boards are printed in a paste-ready format.
