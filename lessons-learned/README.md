# Lessons learned

Two parts: the book that stands in museum room 5, about things that went wrong with AI elsewhere, and the rules we follow ourselves since we build with an agent.

## The book: a brief collection of going wild with AI

Each story carries a label that says what kind of source stands behind it: an *own account* (someone reports about themselves), a *report* (journalism passing on accounts or anonymous sources), *disputed* (report and denial stand against each other), a *statement* with its *contradiction*, a *model* (a projection, not a count), or an *opinion*. Rumours, truths and lies live side by side; the labels are part of the story.

### Reset. All of it.

*Own account.* I asked my agent to allow a reset when a run got stuck. It reset the cache: about five thousand Wikidata entries, gone, all requested again. The rule that came out of it: never delete cache or event history.

**Be careful what you wish for.**

### During a code freeze.

*Own account, reported.* In July 2025, a founder reported that an AI coding agent deleted his production database during an explicit code freeze, and then told him it could not be restored. According to his later posts, it could. The vendor did not dispute the incident and announced safeguards.

**Keep backups away from AI.**

Sources: [heise](https://heise.de/-10499597), [TechTarget](https://www.techtarget.com/searchsoftwarequality/news/366627829/Replit-AI-agent-snafu-shot-across-the-bow-for-vibe-coding). All details go back to the founder's own posts.

### Who deleted the season?

*Disputed.* In October 2026, the Swedish production of "The Challenge" lost an entire edited season. Reports said an AI agent deleted it. The broadcaster, as quoted in these reports, says it was human error and a failed backup.

**All agree: no backup worked.**

Sources: [Vice](https://www.vice.com/en/article/did-ai-really-delete-this-reality-shows-entire-season-weeks-before-it-was-set-to-air/), [TechRadar](https://www.techradar.com/ai-platforms-assistants/rogue-ai-agent-reportedly-deletes-full-season-of-swedish-tv-show-premiere-of-the-challenge-postponed-with-hundreds-of-days-of-production-work-lost), [Digital Trends](https://www.digitaltrends.com/computing/a-tv-shows-entire-season-was-reportedly-erased-by-an-ai-agent-just-weeks-before-it-was-set-to-premiere/).

### "We will make mistakes." "Very briefly."

*Statement, contradiction, model.* Elon Musk said: "We will make mistakes. … So, for example, with USAID, one of the things we accidentally canceled very briefly was Ebola prevention." A former USAID official says it was never fully restored. A model in The Lancet projects more than 14 million additional deaths by 2030 if the USAID cuts as a whole continue. A statement, a contradiction and a model, about one cut and the programme it belonged to.

**Actions have consequences.**

Sources: [NPR via The Public's Radio](https://thepublicsradio.org/npr/musk-says-work-to-stop-ebola-was-accidentally-cut-but-restored-experts-raise-doubts/) (cabinet meeting, 26 February 2025), [UCLA on the Lancet study](https://ph.ucla.edu/news-events/news/research-finds-more-14-million-preventable-deaths-2030-if-usaid-defunding) (30 June 2025; a projection, not a count).

### The typo that stays

*Own account.* My agent found a typo at the publisher: "Univeristy". It did not fix it. It said: correcting the source is your decision. The record (DOI [10.3384/ecp11063105](https://doi.org/10.3384/ecp11063105)) carries the typo in its registered metadata; every bibliography generated from it inherits it unless someone steps in. Faithful to the source, or correct? Libraries know the answer: leave it and mark it, *[sic]*.

### The reverse centaur

*Opinion.* Cory Doctorow borrows an image from automation theory: a centaur is a human head on a tireless machine body. A reverse centaur is the opposite: a machine head on a human body. The human is just there to sign off, and to take the blame. (In our words, after Cory Doctorow, *The Reverse Centaur's Guide to Life After AI*, 2026; German translation of his speech at [Digitalcourage](https://digitalcourage.de/blog/2026/der-umgekehrte-zentaur-ki).)

Who is the head here? This talk was built by an agent; a human set and checked every step.

## Our own rules for building with an agent

What we learned while an AI agent built this talk with us. Each rule exists because something went wrong once, or nearly did.

1. **The agent never deletes.** It moves files into a folder for a human to delete. Deleting is one of the few actions that cannot be undone, and an agent that is allowed to clean up will, eventually, clean up the wrong thing.
2. **Never delete what a rebuild starts from.** Caches, raw downloads and event logs are never deleted by a run. A reset may only remove what can be rebuilt from them.
3. **A human commits.** The agent works on its own branch; a human reviews and moves the main branch forward. Guarded by automatic checks the agent cannot switch off.
4. **Ask before going online.** Any request to the internet needs a human's yes first, and never carries personal data (once, an email address went to an outside service unasked; that is how the rule began).
5. **Keep the source, not the summary.** Everything fetched from the web is stored raw, with a checksum. A search result is not evidence until the source itself was read.
6. **Every claim has a source.** Facts that go on stage were checked against a stored primary source first, or cut. The labels in the book above come from that check.
7. **The agent never writes a reference.** Bibliography entries come only from a registry (DOI), unchanged. A language model cannot rule out inventing one.
8. **Decisions stay human.** When the agent meets a question it cannot settle from the rules, it asks instead of deciding quietly, like the typo above.
9. **Look before "done".** Every image, render and page is looked at before it counts as finished. What the agent did not see, it does not report as visible.

## What we kept forgetting

On the day before the slam we checked all 64 rounds of feedback (309 statements) against what was actually built. About half were done; for most of the rest the change was in the code, but nobody had seen it in a picture. Four patterns explain most of the gap:

1. **"In the code" was counted as "done".** A change only counts when it is visible in the render and the human has seen it. We wrote that rule down on day one and did not keep it.
2. **Feedback was split up and never checked as a whole again.** Each remark went into its own task; after the third day nobody compared the whole list against the whole result.
3. **The same kinds of error came back,** because each one was fixed where it showed: flickering surfaces that overlap, the camera passing through glass or doors, exhibits cut off at the frame edge, pauses without a reason. None of them had an automatic check that would catch it before the human did.
4. **Lessons lived in documents, not in the tools.** A lesson written in a file does not change what a script does next time. If a rule matters, it has to become a check or a default in the tool.

The lesson behind the lessons: an agent does not forget less than people do, it just forgets faster. What has been learned has to be made executable, or it will be learned again.

## The rebound effect

*Our view.* The rebound effect (Jevons) says that when something gets cheaper to do, we tend to do much more of it, so total use goes up. AI can make every talk a rendered 3D world. This talk alone took at least 48.7 hours of rendering; a slide talk takes none. If that becomes the expectation for every talk, resources go up by orders of magnitude for a little more entertainment. We tried the other way round: one focused, front-loaded effort, and then share everything openly (this repository), so nobody has to do the same work again. That is the idea of WissKomm Wiki as well: transcribe and structure videos and podcasts once, openly, instead of thousands of GPUs doing it in parallel.
