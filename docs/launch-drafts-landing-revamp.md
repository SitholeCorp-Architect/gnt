# Launch drafts: landing page + README revamp

Drafts only. Nothing here gets posted by an agent, to anywhere. Review, edit, post yourself
once the revamp actually ships.

## X / Twitter post

```
gnt turns what your team already knows into rules an AI agent has to check before it acts.
every rule goes live through a real, human-merged PR. no dashboard toggle, no separate
"publish" step.

just cleaned up the landing page and README so that loop reads in the first screen instead
of the fifth. git clone, run setup.sh, self-hosted in one script.

github.com/gnt-ai/gnt
```

Keep it close to this length. Cut the second paragraph if it needs to get shorter, the first
one is the actual pitch.

## dev.to-style post outline

**Headline options (pick one):**
- "We rewrote gnt's landing page because the pitch was buried on page one"
- "Nobody understood what gnt does until we led with the terminal, not the feature list"

**Bullets (expand each into a short paragraph, 3-4 total, not a full essay):**

1. **The problem with the old page.** It opened with generic framing (AI governance, agent
   safety) before ever showing the actual mechanic: a rule becomes a markdown file, opens as a
   PR, a human merges it, an agent queries the merged version. That's the entire product, and
   it was three scrolls down.
2. **What changed.** The 90-second loop (write a rule, gnt opens a PR, a human merges it, an
   agent queries it live) now leads. The real terminal screenshot of `gnt prebrain` scanning a
   repo and opening a PR sits right under the fold, not buried in a "how it works" section
   nobody reaches.
3. **Why this matters for anyone evaluating it cold.** A stranger should be able to tell, from
   the first screen, whether gnt solves their actual problem (a rule an agent ignored, or no
   record of who approved what) without booking a call or reading five paragraphs of framing
   first.
4. **What's still rough, said plainly.** Self-hosting needs Postgres and Redis running
   locally, there's no one-click cloud deploy yet, and the setup script says so instead of
   hiding it. Worth naming here so the post doesn't read like it's hiding the rough edges.

## Show HN

One line, when it's actually time:

```
Show HN: gnt, a git-native rules layer for AI agents (every rule is a reviewed PR)
```

Only post this once the revamped landing page and README are actually live. Show HN is for
something a stranger can go look at right now, not a heads-up that something's coming. Posting
it before the revamp ships means the first thing people see is the old page, which defeats the
point of doing the revamp at all.
