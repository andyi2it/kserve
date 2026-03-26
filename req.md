# The grand plan

Building an ecosystem that will be similar to lovable, bolt.new, etc. but targetting enterprise customers/clients.
Lovable and blot.new are good but they are highly opinionaed in terms of tech stack and have very little flexibility.
We plan to build a platform/ecosystem that can enable starting new projects quickly from scratch and able to get going quickly by making use of agentic systems.
We like the idea of minions from stripe, meta swarm where a swarm agents work together. Explore other such ideas.


## Generate a detailed architectur plan
Deliberate between various architect and developer agents and propose an idea. I want emphasize more on logical architecture rather than physical architecture. The agents may have to interact with various external tools and each client may use different set of tools. Some may use notion vs confluence, jira vs something else. The tools/agents shoul be flexible.

The platform should always produce results in such a way its always verifiable immediately in an automated fashion by making use of linting tools, deploys, tests, etc.

They should have fail safes that could limit the amount of times it can self-retry to avoid exhausting tokens because of a failing loop.

## Should have observability

The built platform should have observability and telemetry as part of it. All agent activities should be monitored and should have an interface to manage it. Refer https://github.com/strongdm/leash for example.


## Explore options like context anchoring
https://martinfowler.com/articles/reduce-friction-ai/context-anchoring.html
How it could aide in terms of tasks.

