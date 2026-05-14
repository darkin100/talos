# Talos: Agentified SDLC - V1 Product Requirements Document

## Executive Summary

**Talos** is a demonstration of a fully autonomous software development lifecycle ("dark factory") where AI agents handle code review, security review, deployment, release notes generation, and error monitoring. The system is designed to validate whether an AI-driven harness can reduce toil in the Route to Live while maintaining quality gates and auditability through git.

**Target Audience**: Conference talk demonstrating patterns and techniques for evaluating agentic SDLCs.

**Deployment Model**: Local Docker execution for demo purposes.

---

## V1 Scope

### Application: Hello World (Go Todo API)
- **Language**: Go
- **Purpose**: Simple REST API for todo list management
- **Storage**: In-memory (no persistent database required)
- **Endpoints**: Basic CRUD operations (GET, POST, PUT, DELETE todos)
- **Observability**: Logs to stdout; metrics collected by Arize Phoenix

### Agents (Dockerized)
All agents run as Docker containers invoked from GitHub Actions.

#### 1. **Code-Review Agent**
- **Trigger**: PR opened
- **Input**: PR diff, file changes, commit messages
- **Output**: Comment on PR with feedback (if any)
- **Pass Criteria**: No significant feedback comments on PR
- **Failure Handling**: Blocks merge if significant issues found

#### 2. **Security-Review Agent**
- **Trigger**: After code-review passes
- **Input**: PR diff, source code changes
- **Output**: Comment on PR with security findings (if any)
- **Pass Criteria**: No comments on PR (clean security review)
- **Failure Handling**: Blocks merge if security issues found

#### 3. **Release-Notes Generator Agent**
- **Trigger**: After merge, before deployment
- **Input**: Merged commit messages, PR titles, changes
- **Output**: Generated release notes (stored as GitHub release or file)
- **Pass Criteria**: Successfully generates notes
- **Failure Handling**: Logs failure; doesn't block deployment (informational only for V1)

#### 4. **Route-Course Analysis (RCA) Agent**
- **Trigger**: After deployment completes
- **Input**: 
  - Application logs (stdout/stderr)
  - Arize Phoenix structured metrics
- **Output**: GitHub issue creation if errors detected
- **Pass Criteria**: No errors in logs/metrics
- **Failure Handling**: Creates GitHub issue; marks build as failed (pauses Route to Live)

### Observability: Arize Phoenix
- **Purpose**: Monitor application health and agent performance
- **Integration**: 
  - Captures application logs and metrics
  - RCA queries Phoenix to identify error patterns
  - Provides visibility into agent execution and outcomes
- **Deployment**: Runs alongside Go API in Docker network

---

## V1 Workflow (End-to-End)

```
1. Developer opens PR (triggers GitHub Actions)
   ↓
2. Code-Review Agent
   - Analyzes diff
   - Comments on PR if issues found
   ↓ (pass only)
3. Security-Review Agent
   - Analyzes for security issues
   - Comments on PR if findings exist
   ↓ (pass only)
4. Auto-Merge PR
   - Merges PR if both agents passed
   ↓
5. Release-Notes Generator
   - Creates release notes from commits
   - Outputs to GitHub release
   ↓
6. Deploy Application
   - Deploys Go API + Arize Phoenix to local Docker network
   ↓
7. Route-Course Analysis (RCA)
   - Monitors logs for 60 seconds (configurable)
   - Queries Arize Phoenix for error metrics
   - If errors found:
     * Identifies error source in codebase
     * Creates GitHub issue with RCA findings
     * Marks build as failed
   ↓
8. Success
   - All checks passed
   - Application deployed and healthy
   - Ready for next iteration
```

---

## Success Criteria for V1

### Must-Have (Conference Demo)
- [ ] Go todo API deployed and operational locally
- [ ] Code-review agent comments on PR with meaningful feedback
- [ ] Security-review agent detects and reports security issues
- [ ] PR auto-merges when both agents pass
- [ ] Release-notes agent generates notes from commits
- [ ] Application deploys successfully after merge
- [ ] RCA detects errors in application logs and Arize Phoenix
- [ ] RCA creates GitHub issue with root cause analysis
- [ ] Entire workflow auditable in git (commits, PRs, issues, logs)

### Nice-to-Have (Post-V1)
- [ ] Agent self-iteration on failures (dark factory optimization)
- [ ] Custom metrics for measuring SDLC improvement
- [ ] Multi-agent orchestration patterns
- [ ] Self-healing workflows

---

## Technical Architecture

### Component Diagram
```
GitHub Actions (Orchestrator)
├── Code-Review Container
├── Security-Review Container
├── Release-Notes Container
└── RCA Container
    
Docker Network (Local Demo)
├── Go Todo API (in-memory)
├── Arize Phoenix
└── Log aggregation
```

### Docker Containers
| Agent | Image | Input | Output |
|-------|-------|-------|--------|
| code-review | `talos/code-review:v1` | PR diff | PR comment |
| security-review | `talos/security-review:v1` | PR diff | PR comment |
| release-notes | `talos/release-notes:v1` | Commits | GitHub release |
| rca | `talos/rca:v1` | Logs + metrics | GitHub issue |

### GitHub Actions Workflow
- Trigger: `pull_request` (opened, synchronize)
- Steps:
  1. Checkout code
  2. Build Go API (validate)
  3. Run code-review container
  4. Run security-review container (if code-review passes)
  5. Merge PR (if both pass)
  6. Deploy Go API + Arize Phoenix
  7. Generate release notes
  8. Run RCA monitoring
  9. Report results

---

## Integration Points

### Agent ↔ GitHub
- Agents authenticate with GitHub API
- Comments added to PR via API
- Issues created for RCA findings
- Repo status checks updated

### Application ↔ Arize Phoenix
- Go API emits structured logs
- OpenTelemetry integration (optional for V1, docs included)
- Phoenix ingests and indexes logs/metrics
- RCA queries Phoenix API

### Git Auditability
- All agent actions tracked via:
  - PR comments (visible in GitHub)
  - Merged commits (with agent metadata)
  - GitHub issues (RCA findings)
  - Workflow logs (GitHub Actions)

---

## Failure Handling (V1)

**No self-iteration in V1.** Failures pause the Route to Live via build status:

| Failure Point | Behavior |
|---------------|----------|
| Code-review fails | PR comment added; merge blocked |
| Security-review fails | PR comment added; merge blocked |
| Deploy fails | Build marked failed; RCA doesn't run |
| RCA detects errors | GitHub issue created; build marked failed |

**Auditability**: All failures logged and visible in:
- GitHub Actions workflow runs
- PR comments and review history
- GitHub issues (for RCA findings)
- Git commit log

---

## Repository Structure

```
talos/
├── README.md
├── PRD.md (this file)
├── hello-world/
│   ├── main.go
│   ├── go.mod
│   └── Dockerfile
├── agents/
│   ├── code-review/
│   │   ├── Dockerfile
│   │   └── main.py (or Go)
│   ├── security-review/
│   │   ├── Dockerfile
│   │   └── main.py (or Go)
│   ├── release-notes/
│   │   ├── Dockerfile
│   │   └── main.py (or Go)
│   └── rca/
│       ├── Dockerfile
│       └── main.py (or Go)
├── observ/
│   ├── docker-compose.yml (Arize Phoenix + logging)
│   └── config/
├── .github/
│   └── workflows/
│       └── talos-sdlc.yml (main workflow)
└── scripts/
    └── local-demo.sh (setup + run locally)
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Go todo API (hello-world)
- [ ] GitHub Actions workflow skeleton
- [ ] Local Docker network setup

### Phase 2: Agents (Week 2)
- [ ] Code-review agent (Docker container)
- [ ] Security-review agent (Docker container)

### Phase 3: Deployment & Observability (Week 3)
- [ ] Deploy step in workflow
- [ ] Arize Phoenix setup
- [ ] Release-notes agent

### Phase 4: RCA & Polish (Week 4)
- [ ] RCA agent implementation
- [ ] End-to-end testing
- [ ] Conference demo materials

---

## Success Metrics (to be defined post-V1)

The following will be evaluated after V1 MVP:
- Time from PR open to deployment
- False positive rate (agent feedback accuracy)
- RCA detection rate (errors caught)
- Git auditability (completeness of action trail)

---

## Out of Scope for V1

- Self-iterative agent fixes (dark factory optimization)
- Multi-branch/environment deployments
- Production deployment (local only)
- Agent performance tuning
- Custom metrics dashboard
- Rollback automation

---

## Assumptions & Dependencies

- Developers have Docker installed locally
- GitHub Actions available (no self-hosted runners required for demo)
- Arize Phoenix can run in Docker (open-source or managed)
- Agents communicate via GitHub API and stdout/stderr

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Agents too slow for demo | Poor UX | Pre-run agents in sandbox; cache results |
| Agent accuracy issues | Loss of credibility | Human review of agent output before demo |
| Arize Phoenix setup complex | Delays V1 | Use simplified observability if needed |
| GitHub API rate limits | Workflow failures | Mock GitHub API for demo |

---

## Conference Talk Narrative

**Talos demonstrates:**
1. How to orchestrate agents in CI/CD
2. Building evaluation frameworks for agent quality
3. Patterns for auditability and failure handling
4. Measuring ROI of agentic SDLC

**Key Takeaways for Audience:**
- Agents are "toil destroyers," not "magic" (validation is critical)
- Gates and observability are non-negotiable
- Git is your source of truth for audit trails

---

## Appendix: Agent Specification Template

Each agent follows this contract:

**Input**: GitHub event (PR opened/updated) or webhook
**Processing**: 
  - Fetch PR diff / source code
  - Run analysis (code quality / security / etc.)
  - Format findings

**Output**: PR comment with structured feedback
```
<!-- Agent: code-review | Status: PASS | Findings: 0 -->
No significant issues found.
```

**Exit Code**: 
- `0` = pass
- `1` = fail (with comment)

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-14  
**Status**: Ready for Implementation
