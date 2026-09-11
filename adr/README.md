# Decision log (`ADR-FIA-*`)

Decisions owned by **this repo**: what this package derives, what a capability declares, and where
the line between the two sits.

Not here: how a capability models itself (its own maps own that), and how the ecosystem's artifacts
are named or placed (`ADR-ECO-*` in
[`ecosystem-governance`](https://github.com/papeete-foundry/ecosystem-governance)).

## The log

| ID | Title | Status |
|----|-------|--------|
| [ADR-FIA-0001](./ADR-FIA-0001-the-machinery-leaves-the-capability.md) | The machinery leaves the capability — a published actor any capability can instantiate | Accepted |
| [ADR-FIA-0002](./ADR-FIA-0002-testing-leaves-this-actors-contract.md) | Testing leaves this actor's contract — a component declares what is built, not how it is verified | Accepted |
| [ADR-FIA-0003](./ADR-FIA-0003-the-dev-test-agreement-has-no-home-yet.md) | The dev↔test agreement has no home yet — and it is not this actor's to emit | Superseded by 0004 |
| [ADR-FIA-0004](./ADR-FIA-0004-the-three-amigos-round.md) | The three amigos round — the tester proposes, this actor answers, a human breaks the tie | Accepted |

## Authoring

Copy [`template.md`](./template.md), take the next `NNNN`, keep it short, and link the canonical
source where the decision is implemented rather than restating it.
