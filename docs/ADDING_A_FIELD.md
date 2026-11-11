# Adding a field (for agents)

A "New field" issue asks for a public daily map of a research area. You draft it; the
owner reviews and merges. A field that files papers badly is worse than no field, so
the PR has to show it works on real data.

## Steps

1. **Claim the issue** and work in your own worktree, on a branch `field/<id>`.
   `<id>`: short, lower-case, dashes (`speech-translation`).
2. **Draft `fields/<id>/map.toml`** from `examples/starter.toml`:
   - `[arxiv]`: the categories and a wide net of search terms.
   - `[filter] topic`: what makes a paper about this field at all; `exclude` for
     look-alikes named in the issue.
   - 4–10 `[[subfield]]` rules, specific first, broadest last (with `weight < 1`).
   - Leave `[cards]` out unless the issue's scope clearly needs Figure 4 — every
     card is an LLM call that the project pays for.
   - No `notes.toml`: hand notes are the owner's to write.
3. **Run it for real** into a scratch directory, never into `data/`:

   ```bash
   LS_MAP=fields/<id>/map.toml LS_NOTES=none LS_DATA=<scratch> python3 scripts/fetch.py
   ```

4. **Check the result, and iterate on the rules** until all of these hold:
   - Every paper named in the issue is in the output (or the PR says why not).
   - Read 30 random papers from the output: at most 3 do not belong.
   - No subfield is the *main* subject (`tags[0]`) of more than ~50% of the papers —
     a rule that wins everything says nothing — and none is empty. A deliberate
     catch-all (last, `weight < 1`) may *touch* almost every paper; that is fine.
   - No WARNING about the result cap in the log.
5. **Open the PR** with: the counts per subfield, the 30-paper sample with your verdict
   on each, which issue papers were found, and what you changed between iterations.
   Link the issue. Do not merge it yourself — a new field is public content.
