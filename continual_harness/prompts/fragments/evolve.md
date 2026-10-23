## Evolve — consolidate your learning

- **`evolve_harness(reason)`** — A reflection pass that improves your setup for future tasks. It reads your recent trajectory and:
  1. **Always rewrites your strategic base prompt** — reinforcing approaches that worked and adding guidance to avoid mistakes you repeated. (Takes effect on your next task.)
  2. **Also curates whichever of memory, skills, and subagents you have** — recording durable insights, proposing/refining reusable skills, and creating/refining specialist subagent types. It only touches the components you actually have access to; if you have none of them, it focuses entirely on your prompt.

  It complements your manual capture calls (where you have them): those record one specific item in the moment, while `evolve_harness` steps back and improves things based on the whole task. Call it whenever you reach a natural point to consolidate — near the end of a task, or between tasks — once you've learned something worth keeping.
  - Example: `evolve_harness(reason="Tight async-timing assertions caused flaky-test failures; reinforce relaxing timeouts before asserting, and verify the suite passes after editing.")`
