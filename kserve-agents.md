# Creating a new MCP based agent for KServe

The idea is to create a new MCP based agent for KServe that can allow seamless interaction to KServe for someone directly from chat or terminal from copilot chat or claude cli.

The agent can have gaurdrails on what data can go to remote llm models during query in chat and can also act as a safety net.
It should allow listing isvc, create new ones, manage isvc by updating them like scaling, etc.
Should also be able to seamlessly debug issues by looking at logs, etc.