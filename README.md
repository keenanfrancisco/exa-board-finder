# Exa Board Finder

Find companies with [Exa](https://exa.ai)'s search API, then check each one for a public Greenhouse, Lever, or Ashby job board. It prints the boards you aren't already tracking, in a line format a daily job-scout script can read. Python standard library only.

I built it to feed a job-scout agent that checks a list of company job boards every morning. Before this, finding a company's board meant guessing its slug by hand.

## Setup

Set `EXA_API_KEY` in your shell, or add `EXA_API_KEY=your-key` to `~/.config/exa/env`.

```sh
python3 board_finder.py "defense technology startup in Southern California building drones, missiles, or autonomous systems" --n 25 --known job_scout_companies.txt
```

`--known` (or the `BOARD_FINDER_KNOWN` env var) points at a list of boards you already track, one per line: `greenhouse nerostechnologies name=Neros`. Without it, every board found counts as new.

## Example run (2026-11-09)

The second run of the query above, after the first run's 4 new boards were added to the list:

```
Neros Technologies | neros.tech   | greenhouse | nerostechnologies | 115 | known
Swarm Aero         | swarm.aero   | ashby      | swarmaero         |  48 | NEW
CHIRP Robotics     | linkedin.com | lever      | chirprobotics     |   8 | NEW
CHAOS Industries   | chaosinc.com | greenhouse | chaosindustries   | 173 | known
...
Summary: 25 results, 2 NEW, 6 known, 17 no board.
```

## Things that broke on the way

- **A result pointing at LinkedIn matched LinkedIn's own job board.** Slugs from profile sites (LinkedIn, Crunchbase, etc.) are now skipped in favor of the company name.
- **Boards often don't use the website's name.** Neros is `neros.tech` but its board is `nerostechnologies`. The finder also tries slugs built from the company name.
- **Ashby returns 403 to Python's default User-Agent.** Requests send a custom one, and a test fails if it's removed.

## Tests

```sh
python3 -m unittest -v
```

Network calls are mocked. Built with Codex and Claude: I wrote the spec with Claude, Codex wrote the first version, and the fixes above came from reviewing it and running it against real data.
