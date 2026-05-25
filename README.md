

Whats in a name?  Talos - Hephaestus's bronze automaton, autonomous guardian of Crete.


This repo contains the configuration of a full Agentified SDLC. It's an example
repo, intended to demonstrate the pattern end-to-end rather than be production-
grade.

The exam question:
Is it possible to build a dark factory, and how do I measure/validate
improvements in the harness?

See [PRD.md](PRD.md) for the full design. The repo is laid out as:

```
talos/
├── todo-api/      # demo Node Todo API (Vercel)
├── agents/        # code-review, security-review, release-notes, rca
├── scripts/       # local-demo.sh
└── .github/       # workflows
```

## Basic Assumptions

- The AI Labs will "solve" the coding problem.
- The bottleneck shifts both upstream and downstream of the Route to Live

## Poses set of questions

- What toil in the SDLC can be alleviated with AI Based Automation aka agents?
- How do you validate improvements in the quality of the SDLC harness?


## What this repo is NOT

- It is not a blueprint for the best agents in the world.
- Is not an enterprise ready pattern.


## Technology Selection

- Open source where possible — agents are Python in slim Docker images.
- Metered on OpenRouter; no AI subscriptions required.
- Runtimes packed into GitHub Actions.
- App hosting on Vercel.




Required Reading

- Dark Factory
    https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/

- one-shot, end 2 end coding agents
    https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents

